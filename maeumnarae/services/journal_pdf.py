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
        ids['student'].update(key for key, _ in r.participants)
    labels = {'student': '학생', 'teacher': '교사', 'group': '집단', 'event': '교육/행사'}
    names = {(kind, key): str(key) if kind == 'student' else f'{labels[kind]} {index}' for kind, values in ids.items()
             for index, key in enumerate(sorted(values), 1)}
    return replace(snapshot, records=tuple(replace(r,
        subject=names[(r.subject_type, r.subject_id)],
        participants=tuple((key, str(key)) for key, _ in r.participants),
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
    return journal_story(record)


class FilledContent(Flowable):
    """마지막 내용 칸을 늘려 서명란을 인쇄 영역 하단에 맞춘다."""
    def __init__(self, content, signature, body_offset):
        super().__init__()
        self.content, self.signature, self.body_offset = content, signature, body_offset
        self.natural_heights = list(content._argH)

    def wrap(self, available_width, available_height):
        self.content._spanRects = {}
        self.content._argH = list(self.natural_heights)
        self.content._rowHeights = list(self.natural_heights)
        width, height = self.content.wrap(available_width, available_height)
        _, self.signature_height = self.signature.wrap(available_width, available_height)
        self.reserve = 14 + self.signature_height
        body_row = len(self.content._cellvalues) - self.body_offset
        extra = available_height - height - self.reserve
        if extra >= 0 and body_row >= self.content.repeatRows:
            self.content._argH[body_row] = self.content._rowHeights[body_row] + extra
            self.content._rowHeights = list(self.content._argH)
            self.content._spanRects = {}
            width, height = self.content.wrap(available_width, available_height)
        self.width, self.height = width, height + self.reserve
        return self.width, self.height

    def split(self, available_width, available_height):
        self.content._spanRects = {}
        self.content._argH = list(self.natural_heights)
        self.content._rowHeights = list(self.natural_heights)
        _, height = self.content.wrap(available_width, available_height)
        limit = available_height if height > available_height else available_height - self.reserve
        parts = self.content.split(available_width, limit)
        if len(parts) < 2:
            return []
        return [parts[0], PageBreak(), FilledContent(parts[1], self.signature, self.body_offset)]

    def draw(self):
        self.content.drawOn(self.canv, 0, self.reserve)
        self.signature.drawOn(self.canv, self.width - self.signature._width, 0)


def journal_story(record):
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
    session = f'{record.session_number}회기' if record.session_number else ''
    info = [paragraph('개인상담 일지', fontName='JournalTitle', fontSize=16,
                      leading=24, alignment=TA_CENTER, spaceAfter=6),
            section('▫ 상담정보'),
            row(['학생명', record.subject, '학년·반·번호', enrollment], [.146, .372, .159, .323]),
            row(['상담회기', f'{record.session_number}회기' if record.session_number else '',
                 '상담일시', individual_time(record)], [.146, .166, .139, .549]),
            row(['상담방법', details.get('상담 방법', ''), '상담대상', details.get('상담 대상', ''),
                 '상담분야', details.get('상담 분야', '')], [.146, .166, .139, .166, .142, .241])]
    content_heading, content_label = '상담내용', '내용'
    prefix_rows = []
    if record.kind != 'individual':
        titles = {'special': ('특별교육 일지', '특별교육 정보'), 'test': ('심리검사 일지', '검사정보'),
                  'consultation': ('교원 자문 일지', '자문정보'), 'group': ('집단상담 일지', '집단정보'),
                  'education': ('교육/행사 일지', '교육/행사 정보')}
        title, heading = titles[record.kind]
        info = [paragraph(title, fontName='JournalTitle', fontSize=16, leading=24,
                          alignment=TA_CENTER, spaceAfter=6), section('▫ ' + heading)]
        four = [.146, .372, .159, .323]
        time_row = [.146, .166, .139, .549]
        full = [.146, .854]
        if record.kind == 'special':
            info += [row(['특별교육명', details.get('사례/교육명', ''), '관련법령', details.get('근거 법률', '')], four),
                     row(['학생명', record.subject, '학년·반·번호', enrollment], four),
                     row(['교육회기', session, '교육일시', individual_time(record)], time_row),
                     row(['교육대상', details.get('상담 대상', ''), '-', ''], time_row)]
            info[-1].setStyle(TableStyle([('SPAN', (2, 0), (3, 0)),
                                         ('BACKGROUND', (2, 0), (3, 0), colors.HexColor('#d9d9d9'))]))
            content_heading = content_label = '교육내용'
        elif record.kind == 'test':
            info += [row(['학생명', record.subject, '학년·반·번호', enrollment], four),
                     row(['검사일시', individual_time(record), '검사대상', details.get('검사 대상', '')], [.146, .48, .159, .215]),
                     row(['검사명', record.title], full)]
            content_heading, content_label = '검사결과', '검사결과\n및\n소견'
        elif record.kind == 'consultation':
            info += [row(['교사성명', record.subject, '자문분야', details.get('자문 분야', '')], four),
                     row(['자문회기', session, '자문일시', individual_time(record)], time_row)]
        elif record.kind == 'education':
            count = details.get('참여 인원', '')
            info += [row(['구분', details.get('유형', ''), '교육/행사명', record.title], [.146, .166, .18, .508]),
                     row(['일시', individual_time(record), '장소', details.get('장소', '')], [.146, .424, .14, .29]),
                     row(['대상', details.get('대상', ''), '참여인원', f'{count}명' if count else '',
                          '담당자/강사', details.get('담당자 / 강사', '')], [.146, .166, .139, .166, .162, .221])]
            content_heading = '상세내용'
        elif record.kind == 'group':
            members = ', '.join(name for _, name in record.participants) or ', '.join(a['name'] for a in record.attendance)
            info += [row(['집단명', record.subject, '진행자', details.get('담당자 / 강사', '')], four),
                     row(['상담영역', details.get('상담 분야', ''), '운영기간', details.get('운영기간', '').replace(' - ', ' ~ ')], time_row),
                     row(['상담목표', details.get('상담목표', '')], full), row(['참여학생', members], full)]
            content_heading, content_label = session or '상담회기', '상담내용'
            prefix_rows = [[cell('상담날짜', True), cell(individual_time(record))],
                           [cell('출석학생', True), cell(', '.join(a['name'] for a in record.attendance if a['attended']))]]
    body = rich_blocks(record.content, record.content_format, width - width * .146 - 14)
    follow_rows = [] if record.kind == 'test' else [[cell('후속조치', True), paragraph(record.follow_up, spaceAfter=0)]]
    row_count = len(prefix_rows) + 2 + len(follow_rows)
    content = form_table([[paragraph('▫ ' + content_heading, fontName='JournalTitle', spaceAfter=0), ''],
                          *prefix_rows, [cell(content_label, True), body or [cell('')]],
                          *follow_rows],
                         [width * .146, width * .854], [(0, i) for i in range(row_count)] + [(1, 0)], grid=False)
    content.repeatRows = 1
    # 날짜·출석 행 뒤의 긴 본문을 먼저 나누어 같은 페이지에 제목이 재출력되지 않게 한다.
    if prefix_rows:
        content.splitByRow = 0
    content.setStyle(TableStyle([
        ('SPAN', (0, 0), (-1, 0)), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), .12 * mm, colors.black),
        ('LINEBEFORE', (1, 1), (1, -1), .5, colors.black),
        *[('LINEABOVE', (0, i), (-1, i), .5, colors.black) for i in range(2, row_count)],
    ]))
    if record.kind == 'education':
        content = form_table([[paragraph('▫ 상세내용', fontName='JournalTitle', spaceAfter=0)],
                              [rich_blocks(record.content, record.content_format, width - 14) or [cell('')]]],
                             [width], [(0, 0)], grid=False)
        content.repeatRows = 1
        content.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, 0), .12 * mm, colors.black),
                                     ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    signature = form_table([[cell('작성자', True), cell(f'{record.author} (인)')]],
                           [width / 6, width / 3], [(0, 0)])
    signature.hAlign = 'RIGHT'
    return [*(info if record.kind == 'group' else [KeepTogether(info)]), Spacer(1, 12),
            FilledContent(content, signature, 1 if record.kind in ('test', 'education') else 2)]


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
    first_template = 'Journal' if request.school_year is not None else 'Form'
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
            story += [NextPageTemplate('Form'), PageBreak()]
        header = f'{KINDS[record.kind]} · {record.subject}'
        if record.kind != previous_kind:
            story.append(Heading(KINDS[record.kind], f'kind-{record.kind}', 0, header))
        subject_key = (record.kind, record.subject_id)
        if subject_key != previous_subject:
            story.append(Heading(record.subject, f'subject-{record.kind}-{record.subject_id}', 1, header))
        previous_kind, previous_subject = record.kind, subject_key
        story.extend(journal_story(record))

    def page_end(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor('#52636a'))
        if doc.pageTemplate.id == 'Form':
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
        PageTemplate(id='Form', frames=[Frame(30*mm, 30*mm, INDIVIDUAL_WIDTH,
        A4[1]-65*mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPageEnd=page_end)]
    document.addPageTemplates(sorted(templates, key=lambda template: template.id != first_template))
    document.build(story)
    return output.getvalue()
