"""홈 위젯 등록부. 각 위젯의 UI와 동작은 개별 모듈에서 관리한다."""

from widgets.memo import Memo
from widgets.meal import Meal
from widgets.digital_clock import DigitalClock
from widgets.todo_list import TodoList
from widgets.teacher_search import TeacherSearch

WIDGETS = {widget.kind: widget for widget in (DigitalClock, TodoList, TeacherSearch, Meal, Memo)}
