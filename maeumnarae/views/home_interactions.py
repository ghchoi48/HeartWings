"""포인터 이동 중 미리 보고, 완료 시 한 번만 배치를 저장한다."""

POINTER = r'''(event) => {
    if (event.button !== 0 || event.target.closest('.q-btn')) return;
    const handle = event.currentTarget;
    const card = handle.closest('.home-widget');
    const grid = card.parentElement;
    if (getComputedStyle(grid).gridTemplateColumns.split(' ').length !== 24) return;
    event.preventDefault();
    event.stopPropagation();
    const axis = handle.dataset.resizeAxis || 'move';
    const step = (grid.clientWidth + 8) / 24;
    const origin = {x: +card.dataset.x, y: +card.dataset.y,
                    width: +card.dataset.width, height: +card.dataset.height};
    let size = {...origin}, moved = false;
    const originalStyle = card.getAttribute('style');
    const startX = event.clientX, startY = event.clientY;
    handle.setPointerCapture(event.pointerId);
    card.classList.add('home-resizing');
    const move = e => {
        const dx = e.clientX - startX, dy = e.clientY - startY;
        if (Math.abs(dx) + Math.abs(dy) < 4) return;
        moved = true;
        if (axis === 'move') {
            size.x = Math.max(0, Math.min(24 - size.width, origin.x + Math.round(dx / step)));
            size.y = Math.max(0, origin.y + Math.round(dy / step));
        } else {
            if (axis !== 'y') size.width = Math.max(1, Math.min(24 - size.x, origin.width + Math.round(dx / step)));
            if (axis !== 'x') size.height = Math.max(160, Math.min(1600, (Math.ceil(origin.height / 40) + Math.round(dy / step)) * 40));
        }
        card.style.gridColumn = `${size.x + 1} / span ${size.width}`;
        card.style.gridRow = `${size.y + 1} / span ${Math.ceil(size.height / 40)}`;
        card.style.height = `${Math.ceil(size.height / 40) * step - 8}px`;
        handle.setAttribute('aria-label', `가로 ${size.x + 1}칸, 세로 ${size.y + 1}칸, 너비 ${size.width}칸, 높이 ${Math.ceil(size.height / 40)}칸`);
    };
    const finish = e => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', finish);
        handle.removeEventListener('pointercancel', finish);
        handle.removeEventListener('lostpointercapture', finish);
        card.classList.remove('home-resizing');
        if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
        card.setAttribute('style', originalStyle);
        if (e.type === 'pointerup' && moved) emit(size);
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', finish);
    handle.addEventListener('pointercancel', finish);
    handle.addEventListener('lostpointercapture', finish);
}'''

KEYBOARD = r'''(event) => {
    if (event.target.closest('.q-btn')) return;
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const handle = event.currentTarget;
    const card = handle.closest('.home-widget');
    if (getComputedStyle(card.parentElement).gridTemplateColumns.split(' ').length !== 24) return;
    const axis = handle.dataset.resizeAxis || 'move';
    let x = +card.dataset.x, y = +card.dataset.y;
    let width = +card.dataset.width, height = +card.dataset.height;
    const dx = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    const dy = event.key === 'ArrowDown' ? 1 : event.key === 'ArrowUp' ? -1 : 0;
    if (axis === 'move') {
        x = Math.max(0, Math.min(24 - width, x + dx));
        y = Math.max(0, y + dy);
    } else {
        if (axis !== 'y') width = Math.max(1, Math.min(24 - x, width + dx));
        if (axis !== 'x') height = Math.max(160, Math.min(1600, (Math.ceil(height / 40) + dy) * 40));
    }
    emit({x, y, width, height});
}'''
