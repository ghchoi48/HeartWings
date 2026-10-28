"""외부 브라우저/네트워크 없이 인쇄용 A4 PDF를 메모리에서 생성한다."""
from dataclasses import replace
from html import escape
from html.parser import HTMLParser
from io import BytesIO
from threading import Lock
from datetime import timedelta

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Paragraph, Spacer, PageBreak, LongTable,
                               TableStyle, Flowable, NextPageTemplate, KeepTogether)

from maeumnarae.core.paths import RESOURCE_ROOT
from maeumnarae.services.journal_print_models import KINDS, STATUSES, PrintSnapshot
from maeumnarae.views.counseling_content import editor_html
from maeumnarae.services.reporting import KST

_font_lock = Lock()
WIDTH = A4[0] - 30 * mm
INDIVIDUAL_WIDTH = A4[0] - 60 * mm


def register_fonts():
    with _font_lock:
        if 'Journal' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('Journal', str(
                RESOURCE_ROOT / 'fonts' / 'RIDIBatang' / 'HeartWingsRidiBatang-Regular.ttf')))
            # 리디바탕은 Regular만 제공하므로 굵은 강조는 기존 글꼴을 사용한다.
            pdfmetrics.registerFont(TTFont('JournalBold', str(
                RESOURCE_ROOT / 'fonts' / 'JournalSans' / 'JournalSans-Bold.ttf')))
            pdfmetrics.registerFontFamily('Journal', normal='Journal', bold='JournalBold', italic='Journal', boldItalic='JournalBold')
        if 'JournalTitle' not in pdfmetrics.getRegisteredFontNames():
            # 번들 Noto Sans KR의 정적 700 인스턴스 (JournalSans/README.txt).
            pdfmetrics.registerFont(TTFont('JournalTitle', str(
                RESOURCE_ROOT / 'fonts' / 'JournalSans' / 'JournalSans-Bold.ttf')))


def style(**kwargs):
    return ParagraphStyle('journal', **dict(dict(fontName='Journal', fontSize=10, leading=16,
                          wordWrap='CJK', spaceAfter=6), **kwargs))


def paragraph(text, **kwargs):
    return Paragraph(escape(str(text)).replace('\n', '<br/>') or ' ', style(**kwargs))


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []


class Tree(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in ('br', 'hr', 'img', 'input', 'meta', 'link', 'wbr'):
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def inline(node):
    if isinstance(node, str):
        return escape(node)
    if node.tag in ('script', 'style', 'img', 'iframe', 'object'):
        return ''
    if node.tag == 'br':
        return '<br/>'
    body = ''.join(inline(child) for child in node.children)
    tag = {'strong': 'b', 'em': 'i', 'del': 'strike', 's': 'strike'}.get(node.tag, node.tag)
    css = node.attrs.get('style', '')
    if tag in ('b', 'i', 'u', 'strike', 'sub', 'sup'):
        body = f'<{tag}>{body}</{tag}>'
    if 'bold' in css or '700' in css:
        body = f'<b>{body}</b>'
    if 'italic' in css:
        body = f'<i>{body}</i>'
    if 'underline' in css:
        body = f'<u>{body}</u>'
    return body


def table(rows, widths=None, header=True):
    result = LongTable(rows, colWidths=widths, repeatRows=1 if header else 0,
                       hAlign='LEFT', splitByRow=1, splitInRow=1)
    result.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#cbd5d1')),
        ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        *([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf6f3'))] if header else []),
    ]))
    return result


def rich_blocks(content, content_format='html', width=WIDTH):
    root = Tree(editor_html(content, content_format)).root
    blocks = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre', 'ul', 'ol', 'table', 'hr'}

    def walk(node, available):
        output, pending = [], []

        def flush():
            text = ''.join(inline(item) for item in pending)
            if text.strip():
                css = node.attrs.get('style', '')
                align = TA_CENTER if 'center' in css else TA_RIGHT if 'right' in css else TA_LEFT
                output.append(Paragraph(text, style(alignment=align)))
            pending.clear()

        for child in node.children:
            if isinstance(child, str) or child.tag not in blocks:
                pending.append(child)
                continue
            flush()
            if child.tag in ('ul', 'ol'):
                for number, item in enumerate((n for n in child.children if isinstance(n, Node) and n.tag == 'li'), 1):
                    label = f'{number}. ' if child.tag == 'ol' else '• '
                    output.append(Paragraph(escape(label) + inline(item), style(leftIndent=10)))
            elif child.tag == 'table':
                def find_rows(n):
                    for c in n.children:
                        if isinstance(c, Node):
                            if c.tag == 'tr':
                                yield c
                            else:
                                yield from find_rows(c)
                raw = [[c for c in row.children if isinstance(c, Node) and c.tag in ('td', 'th')]
                       for row in find_rows(child)]
                count = max((len(row) for row in raw), default=0)
                if count:
                    rows = [[walk(cell, available / count - 14) or [paragraph('')] for cell in row] +
                            [[paragraph('')]] * (count - len(row)) for row in raw]
                    output.append(table(rows, [available / count] * count,
                                        header=any(cell.tag == 'th' for cell in raw[0])))
                    output.append(Spacer(1, 6))
            elif child.tag == 'hr':
                output.append(Spacer(1, 8))
            else:
                output.extend(walk(child, available))
        flush()
        return output
    return walk(root, width)


def masked_snapshot(snapshot):
    ids = {'student': set(), 'teacher': set(), 'group': set(), 'event': set()}
    for r in snapshot.records:
        ids[r.subject_type].add(r.subject_id)
        ids['student'].update(a['student_id'] for a in r.attendance)
    labels = {'student': '학생', 'teacher': '교사', 'group': '집단', 'event': '교육/행사'}
    names = {(kind, key): str(key) if kind == 'student' else f'{labels[kind]} {index}' for kind, values in ids.items()
             for index, key in enumerate(sorted(values), 1)}
    return replace(snapshot, records=tuple(replace(r,
        subject=names[(r.subject_type, r.subject_id)],
        attendance=tuple(dict(a, name=names[('student', a['student_id'])]) for a in r.attendance))
        for r in snapshot.records))


def individual_time(record):
    start = record.moment.astimezone(KST)
    if record.minutes is None:
        return start.strftime('%Y-%m-%d %H:%M')
    end = start + timedelta(minutes=record.minutes)
    return start.strftime('%Y-%m-%d %H:%M') + '~' + end.strftime(
        '%H:%M' if start.date() == end.date() else '%Y-%m-%d %H:%M')


def form_table(rows, widths, shaded=(), grid=True):
    result = LongTable(rows, colWidths=widths, hAlign='LEFT', splitByRow=1, splitInRow=1)
    result.setStyle(TableStyle([
        *([('GRID', (0, 0), (-1, -1), .5, colors.black)] if grid else []),
        ('BOX', (0, 0), (-1, -1), .9, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        *[('BACKGROUND', cell, cell, colors.HexColor('#d9d9d9')) for cell in shaded],
    ]))
    return result


def individual_story(record):
    width = INDIVIDUAL_WIDTH
    details = dict(record.details)

    def cell(text, label=False):
        return paragraph(text, alignment=TA_CENTER if label else TA_LEFT,
                         fontSize=9 if label else 10, spaceAfter=0)

    def section(text):
        result = form_table([[paragraph(text, fontName='JournalTitle', spaceAfter=0)]], [width], [(0, 0)])
        result.keepWithNext = True
        return result

    def row(values, ratios):
        return form_table([[cell(v, i % 2 == 0) for i, v in enumerate(values)]],
                          [width * r for r in ratios], [(i, 0) for i in range(0, len(values), 2)])

    enrollment = ' '.join(v for v in (
        f'{record.grade}학년' if record.grade is not None else '',
        f'{record.classroom}반' if record.classroom else '',
        f'{record.student_number}번' if record.student_number else '') if v)
    info = [paragraph('개인상담 일지', fontName='JournalTitle', fontSize=16,
                      leading=24, alignment=TA_CENTER, spaceAfter=6),
            section('▫ 상담정보'),
            row(['학생명', record.subject, '학년·반·번호', enrollment], [.146, .372, .159, .323]),
            row(['상담회기', f'{record.session_number}회기' if record.session_number else '',
                 '상담일시', individual_time(record)], [.146, .166, .139, .549]),
            row(['상담방법', details.get('상담 방법', ''), '상담대상', details.get('상담 대상', ''),
                 '상담분야', details.get('상담 분야', '')], [.146, .166, .139, .166, .142, .241])]
    body = rich_blocks(record.content, record.content_format, width - width * .146 - 14)
    content = form_table([[paragraph('▫ 상담내용', fontName='JournalTitle', spaceAfter=0), ''],
                          [cell('내용', True), body or [cell('')]],
                          [cell('후속조치', True), paragraph(record.follow_up, spaceAfter=0)]],
                         [width * .146, width * .854], [(0, 0), (0, 1), (0, 2), (1, 0)], grid=False)
    content.repeatRows = 1
    content.setStyle(TableStyle([
        ('SPAN', (0, 0), (-1, 0)), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), .12 * mm, colors.black),
        ('LINEBEFORE', (1, 1), (1, -1), .5, colors.black),
        ('LINEABOVE', (0, 2), (-1, 2), .5, colors.black),
    ]))
    signature = form_table([[cell('작성자', True), cell(f'{record.author} (인)')]],
                           [width / 6, width / 3], [(0, 0)])
    signature.hAlign = 'RIGHT'
    return [KeepTogether(info), Spacer(1, 12), content,
            Spacer(1, 14), signature]


class Heading(Flowable):
    def __init__(self, label, key, level, header):
        super().__init__()
        self.label, self.key, self.level, self.header = label, key, level, header
        self.width = self.height = 0

    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.label, self.key, self.level, False)
        self.canv._journal_header = self.header


def build_pdf(snapshot, request):
    request.validate()
    if not snapshot.records:
        raise ValueError('출력할 일지가 없습니다.')
    register_fonts()
    if request.mask_names:
        snapshot = masked_snapshot(snapshot)
    output = BytesIO()
    document = BaseDocTemplate(output, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm,
                                 topMargin=20*mm, bottomMargin=18*mm,
                                 title='마음나래 일지', author='마음나래')
    first_template = 'Journal' if request.school_year is not None else (
        'Individual' if snapshot.records[0].kind == 'individual' else 'Journal')
    story = []
    if request.school_year is not None:
        start, end = request.bounds
        story += [paragraph(f'{request.school_year}학년도 전체 일지', fontName='JournalBold')]
        story += [paragraph(snapshot.school), paragraph(f'{start} ~ {end - timedelta(days=1)}'),
                  paragraph('포함 상태: ' + ', '.join(STATUSES[s] for s in STATUSES if s in request.statuses)),
                  paragraph('상태가 없는 심리검사·교육/행사 포함'),
                  paragraph(f'전체 {len(snapshot.records)}건')]
        story += [paragraph(f'{KINDS[k]}: {n}건') for k, n in snapshot.counts.items() if n]
    previous_kind = previous_subject = None
    for index, record in enumerate(snapshot.records):
        if index or request.school_year is not None:
            story += [NextPageTemplate('Individual' if record.kind == 'individual' else 'Journal'), PageBreak()]
        header = f'{KINDS[record.kind]} · {record.subject}'
        if record.kind != previous_kind:
            story.append(Heading(KINDS[record.kind], f'kind-{record.kind}', 0, header))
        subject_key = (record.kind, record.subject_id)
        if subject_key != previous_subject:
            story.append(Heading(record.subject, f'subject-{record.kind}-{record.subject_id}', 1, header))
        previous_kind, previous_subject = record.kind, subject_key
        if record.kind == 'individual':
            story.extend(individual_story(record))
            continue
        story += [paragraph(f'{KINDS[record.kind]} 일지', fontName='JournalBold'), paragraph(record.title)]
        pairs = [('학교', snapshot.school), ('작성자', record.author), ('대상', record.subject),
                 ('일시', record.moment.strftime('%Y-%m-%d %H:%M')),
                 ('소요 시간', f'{record.minutes}분' if record.minutes is not None else ''),
                 ('상태', STATUSES.get(record.status, '')), *record.details]
        story.append(table([[paragraph(k), paragraph(v)] for k, v in pairs if v != ''], [30*mm, WIDTH-30*mm], False))
        story += [Spacer(1, 10), paragraph('내용', fontName='JournalBold')]
        story.extend(rich_blocks(record.content, record.content_format) or [paragraph('내용 없음')])
        if record.follow_up:
            story += [paragraph('추후 계획', fontName='JournalBold'), paragraph(record.follow_up)]
        if record.attendance:
            story += [paragraph('참여자 출석 및 참여 태도', fontName='JournalBold'),
                      table([[paragraph(v) for v in ('참여자', '출석', '참여 태도')]] +
                            [[paragraph(a['name']), paragraph('출석' if a['attended'] else '미출석'), paragraph(a['attitude'])]
                             for a in record.attendance], [40*mm, 20*mm, WIDTH-60*mm])]

    def page_end(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor('#52636a'))
        if doc.pageTemplate.id == 'Individual':
            organization = 'Wee센터' if snapshot.school_level == 'Wee센터' else 'Wee클래스'
            heading = f'{snapshot.school} {organization}'.strip()
            # 긴 기관명도 생략하거나 축소하지 않고 9pt로 오른쪽 정렬한다.
            header = paragraph(heading, fontSize=9, leading=11, alignment=TA_RIGHT, spaceAfter=0)
            _, height = header.wrap(INDIVIDUAL_WIDTH, A4[1])
            header.drawOn(canvas, 30*mm, A4[1]-12*mm-height)
        else:
            canvas.setFont('Journal', 8)
            heading = getattr(canvas, '_journal_header', '마음나래 일지')
            while pdfmetrics.stringWidth(heading, 'Journal', 8) > WIDTH:
                heading = heading[:-2] + '…'
            canvas.drawString(15*mm, A4[1]-12*mm, heading)
        canvas.setFont('Journal', 8)
        canvas.drawRightString(A4[0]-15*mm, 10*mm, str(doc.page))
        canvas.restoreState()

    # onPageEnd를 사용해야 새 묶음의 첫 페이지 머리말도 정확하다.
    from reportlab.platypus import PageTemplate, Frame
    templates = [PageTemplate(id='Journal', frames=[Frame(15*mm, 18*mm, WIDTH,
        A4[1]-38*mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPageEnd=page_end),
        PageTemplate(id='Individual', frames=[Frame(30*mm, 30*mm, INDIVIDUAL_WIDTH,
        A4[1]-65*mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPageEnd=page_end)]
    document.addPageTemplates(sorted(templates, key=lambda template: template.id != first_template))
    document.build(story)
    return output.getvalue()
