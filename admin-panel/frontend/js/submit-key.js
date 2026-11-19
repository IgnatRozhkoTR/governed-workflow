function isSubmitKeyEvent(e) {
  if (e.key !== 'Enter') return false;
  if (e.isComposing || e.keyCode === 229) return false;
  if (e.ctrlKey || e.metaKey) return true;
  return !e.shiftKey && !e.altKey;
}

function attachSubmitKey(input, submit) {
  input.addEventListener('keydown', function(e) {
    if (!isSubmitKeyEvent(e)) return;
    e.preventDefault();
    if (input.value.trim()) submit();
  });
  var hint = document.createElement('div');
  hint.className = 'submit-key-hint';
  hint.textContent = t('hints.submitKey');
  input.insertAdjacentElement('afterend', hint);
}
