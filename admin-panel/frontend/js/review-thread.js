// ═══════════════════════════════════════════════
//  REVIEW THREAD COMPONENT
// ═══════════════════════════════════════════════

/**
 * Render a review comment thread (root comment + replies).
 * @param {Object} comment - {id, text, author, file_path, line_start, line_end, created_at, resolved, resolved_at, resolution, replies: [{id, text, author, created_at, status}]}
 * @param {Object} options - {
 *   showFileInfo: boolean,     // show file:line badge (for review tab, not for inline diff)
 *   onResolve: function(id),   // called when resolve/unresolve clicked
 *   onReply: function(id, text), // called when reply submitted
 *   onFileClick: function(file_path, line_start, line_end), // called when file badge clicked
 * }
 * @returns {HTMLElement} - the thread DOM element
 */
function reviewAuthorLabel(author) {
  var key = 'author.' + author;
  var translated = t(key);
  if (translated !== key) return translated;
  return author
    .split(/[-_]/)
    .filter(function(part) { return part.length > 0; })
    .map(function(part, idx) {
      if (idx === 0) return part.charAt(0).toUpperCase() + part.slice(1);
      return part;
    })
    .join(' ');
}

function buildReviewAvatar(author) {
  var avatar = document.createElement('span');
  var role = author === 'user' ? '' : (author === 'agent' ? ' ag' : ' rv');
  avatar.className = 'av' + role;
  avatar.textContent = reviewAuthorLabel(author).charAt(0).toUpperCase();
  return avatar;
}

function buildReviewAuthorLine(author, metaParts) {
  var line = document.createElement('div');
  var name = document.createElement('b');
  name.className = 'review-author review-author-' + author;
  name.textContent = reviewAuthorLabel(author);
  line.appendChild(name);
  metaParts.forEach(function(part) {
    line.appendChild(document.createTextNode(' '));
    line.appendChild(part);
  });
  return line;
}

function buildReviewMetaPart(text, className) {
  var part = document.createElement('span');
  part.className = className || 'review-meta';
  part.textContent = text;
  return part;
}

function buildReviewMessage(author, metaParts, text) {
  var message = document.createElement('div');
  message.className = 'cmt';
  message.appendChild(buildReviewAvatar(author));
  var body = document.createElement('div');
  body.className = 'cmt-body';
  body.appendChild(buildReviewAuthorLine(author, metaParts));
  var textEl = document.createElement('div');
  textEl.className = 'review-thread-text';
  textEl.textContent = text;
  body.appendChild(textEl);
  message.appendChild(body);
  return message;
}

function renderReviewThread(comment, options) {
  var opts = options || {};
  var thread = document.createElement('div');
  thread.className = 'review-thread' + (comment.resolved ? ' review-thread-resolved' : '');

  var root = buildReviewMessage(comment.author || 'user', buildReviewRootMeta(comment, opts), comment.text);
  var rootBody = root.querySelector('.cmt-body');
  var replyForm = buildReviewReplyForm(comment, opts);
  rootBody.appendChild(buildReviewActions(comment, opts, replyForm));
  rootBody.appendChild(replyForm);
  thread.appendChild(root);
  (comment.replies || []).forEach(function(reply) {
    thread.appendChild(buildReviewReply(reply));
  });
  return thread;
}

function buildReviewRootMeta(comment, opts) {
  var parts = [];
  if (opts.showFileInfo && comment.file_path) parts.push(buildReviewFileBadge(comment, opts));
  if (comment.created_at) parts.push(buildReviewMetaPart(formatRelativeDate(comment.created_at)));
  if (comment.resolution && comment.resolution !== 'open') {
    parts.push(buildReviewMetaPart(t('review.resolution.' + comment.resolution), 'review-resolution review-resolution-' + comment.resolution));
  }
  return parts;
}

function buildReviewFileBadge(comment, opts) {
  var label = comment.file_path;
  if (comment.line_start) {
    label += ':' + comment.line_start;
    if (comment.line_end && comment.line_end !== comment.line_start) {
      label += '-' + comment.line_end;
    }
  }
  var badge = buildReviewMetaPart(label, 'review-file-badge');
  if (typeof opts.onFileClick === 'function') {
    badge.addEventListener('click', function() {
      opts.onFileClick(comment.file_path, comment.line_start, comment.line_end);
    });
  }
  return badge;
}

function buildReviewActions(comment, opts, replyForm) {
  var actions = document.createElement('div');
  actions.className = 'cmt-actions';

  var replyBtn = document.createElement('button');
  replyBtn.className = 'btn xs review-reply-toggle';
  replyBtn.textContent = t('buttons.reply');
  replyBtn.addEventListener('click', function() {
    replyForm.hidden = !replyForm.hidden;
    if (!replyForm.hidden) replyForm.querySelector('input').focus();
  });
  actions.appendChild(replyBtn);
  actions.appendChild(buildReviewResolveButton(comment, opts));
  return actions;
}

function buildReviewResolveButton(comment, opts) {
  var btn = document.createElement('button');
  btn.className = 'btn xs review-resolve-btn';
  btn.textContent = comment.resolved ? t('comments.unresolve') : t('buttons.resolve');

  if (typeof opts.onResolve === 'function') {
    btn.addEventListener('click', function() {
      opts.onResolve(comment.id);
    });
  }

  return btn;
}

function buildReviewReply(reply) {
  var metaParts = reply.created_at ? [buildReviewMetaPart(formatRelativeDate(reply.created_at))] : [];
  var replyEl = buildReviewMessage(reply.author || 'user', metaParts, reply.text);
  replyEl.classList.add('review-reply');
  return replyEl;
}

function buildReviewReplyForm(comment, opts) {
  var form = document.createElement('div');
  form.className = 'review-reply-form';
  form.hidden = true;

  var input = document.createElement('input');
  input.type = 'text';
  input.className = 'review-reply-input';
  input.placeholder = t('placeholders.replyDots');

  var btn = document.createElement('button');
  btn.className = 'btn xs pri review-reply-btn';
  btn.textContent = t('buttons.reply');

  function submitReply() {
    var text = input.value.trim();
    if (!text) return;
    if (typeof opts.onReply === 'function') {
      opts.onReply(comment.id, text);
    }
    input.value = '';
  }

  input.addEventListener('keydown', function(e) {
    if (isSubmitKeyEvent(e)) {
      e.preventDefault();
      submitReply();
    }
  });

  btn.addEventListener('click', submitReply);

  form.appendChild(input);
  form.appendChild(btn);

  return form;
}
