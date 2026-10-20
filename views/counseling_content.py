"""기존 마크다운과 서식 있는 상담 본문의 표시 변환."""

from html import escape

import markdown2
import nh3


def clean_html(content: str) -> str:
    return nh3.clean(content, attributes={
        '*': {'style'}, 'a': {'href', 'title'},
    }, filter_style_properties={'text-align', 'font-weight', 'font-style', 'text-decoration'})


def editor_html(content: str, content_format: str = 'markdown') -> str:
    if not content:
        return ''
    if content_format == 'text':
        return clean_html(escape(content).replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>'))
    html = content if content_format == 'html' else str(markdown2.markdown(
        content, extras=['fenced-code-blocks', 'tables']))
    return clean_html(html)
