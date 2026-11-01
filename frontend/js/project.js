/**
 * Project Navigator Module
 */

export function initProjectNavigator() {
  const treeDocs = document.getElementById('tree-documents');
  if (treeDocs) {
    treeDocs.addEventListener('click', (e) => {
      const li = e.target.closest('li');
      if (li) {
        treeDocs.querySelectorAll('li').forEach(el => el.classList.remove('active'));
        li.classList.add('active');
        console.log(`Document selected: ${li.textContent.trim()}`);
      }
    });
  }
}
