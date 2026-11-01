/**
 * Contextual Properties Panel Module
 */

export function initPropertiesPanel() {
  const groupBtns = document.querySelectorAll('.group-btn');
  groupBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      const parent = btn.parentElement;
      parent.querySelectorAll('.group-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
  });
}
