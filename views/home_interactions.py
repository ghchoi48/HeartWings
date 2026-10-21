"""홈 위젯 크기 조절: 브라우저에서 미리보기하고 드래그 완료 시 한 번 저장한다."""

RESIZE_POINTER = r'''(event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const handle = event.currentTarget;
    const card = handle.closest('.home-widget');
    const grid = card.parentElement;
    const styles = getComputedStyle(grid);
    const columns = styles.gridTemplateColumns.split(' ').length;
    const gap = parseFloat(styles.columnGap) || 0;
    const cell = (grid.clientWidth - gap * (columns - 1)) / columns;
    const rect = card.getBoundingClientRect();
    const x = event.clientX, y = event.clientY;
    const originalColumn = card.style.gridColumn;
    const originalHeight = card.style.height;
    let span = Math.min(columns, Number(card.dataset.span));
    let height = Math.round(rect.height);
    let moved = false;
    handle.setPointerCapture(event.pointerId);
    card.classList.add('home-resizing');
    const move = e => {
        moved ||= Math.abs(e.clientX - x) + Math.abs(e.clientY - y) > 3;
        span = Math.max(1, Math.min(columns, Math.round((rect.width + e.clientX - x + gap) / (cell + gap))));
        height = Math.max(290, Math.min(900, Math.round((rect.height + e.clientY - y) / 10) * 10));
        card.style.gridColumn = `span ${span}`;
        card.style.height = `${height}px`;
        handle.setAttribute('aria-label', `크기 조절: ${span}열, ${height}px`);
    };
    const finish = e => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', finish);
        handle.removeEventListener('pointercancel', cancel);
        handle.removeEventListener('lostpointercapture', cancel);
        card.classList.remove('home-resizing');
        if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
        if (e.type === 'pointerup' && moved) {
            emit({span, height});
        } else {
            card.style.gridColumn = originalColumn;
            card.style.height = originalHeight;
        }
    };
    const cancel = e => finish(e);
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', finish);
    handle.addEventListener('pointercancel', cancel);
    handle.addEventListener('lostpointercapture', cancel);
}'''

RESIZE_KEYBOARD = r'''(event) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const card = event.currentTarget.closest('.home-widget');
    const span = Number(card.dataset.span);
    const height = parseInt(card.style.height);
    emit({span: Math.max(1, Math.min(3, span + (event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0))),
          height: Math.max(290, Math.min(900, height + (event.key === 'ArrowDown' ? 10 : event.key === 'ArrowUp' ? -10 : 0)))});
}'''
