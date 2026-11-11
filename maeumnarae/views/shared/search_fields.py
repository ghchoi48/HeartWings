"""Search controls that filter during IME composition without losing input."""

from nicegui import ui


def search_input(*args, **kwargs) -> ui.input:
    field = ui.input(*args, **kwargs)
    field.on('input', js_handler=f'''event => {{
        if (event.target?.matches('input') &&
            (event.isComposing || event.target.qComposing)) {{
            getElement({field.id}).inputValue = event.target.value;
        }}
    }}''')
    return field


def search_select(*args, **kwargs) -> ui.select:
    field = ui.select(*args, **kwargs).props('input-debounce=0')
    field.on('input', js_handler=f'''event => {{
        if (event.target?.matches('input') &&
            (event.isComposing || event.target.qComposing)) {{
            const select = getElement({field.id}).$refs.qRef;
            select.updateInputValue(event.target.value, true);
            select.filter(event.target.value);
        }}
    }}''')
    return field
