"""일지 파일 내보내기와 인쇄를 모은 설정 탭."""

from maeumnarae.core.database import Database
from maeumnarae.views.reports.journal_export_view import JournalExportView
from maeumnarae.views.reports.journal_print_view import build_all_print


def build_export_settings(database: Database) -> None:
    JournalExportView(database).build(collapsible=True)
    JournalExportView(database, ledger=True).build(collapsible=True)
    build_all_print(database)
