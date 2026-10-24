"""홈 위젯 등록부. 각 위젯의 UI와 동작은 개별 모듈에서 관리한다."""

from maeumnarae.widgets.weather import Weather
from maeumnarae.widgets.memo import Memo
from maeumnarae.widgets.meal import Meal
from maeumnarae.widgets.digital_clock import DigitalClock
from maeumnarae.widgets.todo_list import TodoList
from maeumnarae.widgets.teacher_search import TeacherSearch

WIDGETS = {widget.kind: widget for widget in (DigitalClock, TodoList, TeacherSearch, Meal, Memo, Weather)}
