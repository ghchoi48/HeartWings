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
from reportlab.platypus import BaseDocTemplate, Paragraph, Spacer, PageBreak, LongTable, TableStyle, Flowable

from maeumnarae.core.paths import RESOURCE_ROOT
from maeumnarae.services.journal_print_models import KINDS, STATUSES, PrintSnapshot
from maeumnarae.views.counseling_content import editor_html

_font_lock = Lock()
WIDTH = A4[0] - 30 * mm


def register_fonts():
    with _font_lock:
        if 'Journal' not in pdfmetrics.getRegisteredFontNames():
            for name, weight in [('Journal', 'Regular'), ('JournalBold', 'Bold')]:
                pdfmetrics.registerFont(TTFont(name, str(RESOURCE_ROOT / 'fonts' / 'JournalSans' / f'JournalSans-{weight}.ttf')))
            pdfmetrics.registerFontFamily('Journal', normal='Journal', bold='JournalBold', italic='Journal', boldItalic='JournalBold')


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
    names = {(kind, key): f'{labels[kind]} {index}' for kind, values in ids.items()
             for index, key in enumerate(sorted(values), 1)}
    return PrintSnapshot(snapshot.school, tuple(replace(r,
        subject=names[(r.subject_type, r.subject_id)],
        attendance=tuple(dict(a, name=names[('student', a['student_id'])]) for a in r.attendance))
        for r in snapshot.records))


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
    story = []
    if request.school_year is not None:
        start, end = request.bounds
        story += [paragraph(f'{request.school_year}학년도 전체 일지', fontName='JournalBold')]
        story += [paragraph(snapshot.school), paragraph(f'{start} ~ {end - timedelta(days=1)}'),
                  paragraph('포함 상태: ' + ', '.join(STATUSES[s] for s in STATUSES if s in request.statuses)),
                  paragraph('상태가 없는 심리검사·교육/행사 포함'),
                  paragraph(f'전체 {len(snapshot.records)}건')]
        story += [paragraph(f'{KINDS[k]}: {n}건') for k, n in snapshot.counts.items() if n]
        story.append(PageBreak())
    previous_kind = previous_subject = None
    for index, record in enumerate(snapshot.records):
        if index:
            story.append(PageBreak())
        header = f'{KINDS[record.kind]} · {record.subject}'
        if record.kind != previous_kind:
            story.append(Heading(KINDS[record.kind], f'kind-{record.kind}', 0, header))
        subject_key = (record.kind, record.subject_id)
        if subject_key != previous_subject:
            story.append(Heading(record.subject, f'subject-{record.kind}-{record.subject_id}', 1, header))
        previous_kind, previous_subject = record.kind, subject_key
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
        canvas.setFont('Journal', 8)
        canvas.setFillColor(colors.HexColor('#52636a'))
        heading = getattr(canvas, '_journal_header', '마음나래 일지')
        while pdfmetrics.stringWidth(heading, 'Journal', 8) > WIDTH:
            heading = heading[:-2] + '…'
        canvas.drawString(15*mm, A4[1]-12*mm, heading)
        canvas.drawRightString(A4[0]-15*mm, 10*mm, str(doc.page))
        canvas.restoreState()

    # onPageEnd를 사용해야 새 묶음의 첫 페이지 머리말도 정확하다.
    from reportlab.platypus import PageTemplate, Frame
    document.addPageTemplates(PageTemplate(id='Journal', frames=[Frame(15*mm, 18*mm, WIDTH,
        A4[1]-38*mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPageEnd=page_end))
    document.build(story)
    return output.getvalue()
