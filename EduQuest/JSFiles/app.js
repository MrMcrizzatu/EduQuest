/* ===== EduQuest — global UI scripts ===== */
var eduQuestText = window.eduQuestText || {};

// ---------- Categories drawer ----------
function openDrawer() {
  document.getElementById('drawer').classList.add('open');
  document.getElementById('drawer-overlay').classList.add('open');
  document.getElementById('drawer').setAttribute('aria-hidden', 'false');
}

function closeDrawer() {
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('drawer-overlay').classList.remove('open');
  document.getElementById('drawer').setAttribute('aria-hidden', 'true');
}

document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    closeDrawer();
    closeAuthModal();
  }
});

// ---------- Auth modal ----------
function openAuthModal(tab) {
  var modal = document.getElementById('auth-modal');
  if (!modal) {
    var mode = tab === 'register' ? 'register' : 'login';
    window.location.href = '/auth?mode=' + encodeURIComponent(mode);
    return;
  }
  modal.classList.add('open');
  switchAuthTab(tab || 'login');
}

function closeAuthModal() {
  var modal = document.getElementById('auth-modal');
  if (!modal) return;
  modal.classList.remove('open');
}

function switchAuthTab(tab) {
  document.querySelectorAll('.modal-tab').forEach(function (b) {
    b.classList.toggle('active', b.dataset.tab === tab);
  });
  var login = document.getElementById('login-form');
  var reg = document.getElementById('register-form');
  if (login && reg) {
    login.classList.toggle('hidden', tab !== 'login');
    reg.classList.toggle('hidden', tab !== 'register');
  }
}

async function submitAuth(event, kind) {
  event.preventDefault();
  var form = event.target;
  var errorEl = document.getElementById(kind + '-error');
  errorEl.classList.add('hidden');
  errorEl.textContent = '';

  var data = new FormData(form);
  var endpoint = kind === 'login' ? '/auth/login' : '/auth/register';
  try {
    var res = await fetch(endpoint, { method: 'POST', body: data });
    var json = await res.json();
    if (json.ok) {
      window.location.href = json.redirect || '/';
    } else {
      errorEl.textContent = json.error || eduQuestText.genericError || 'Error';
      errorEl.classList.remove('hidden');
    }
  } catch (err) {
    errorEl.textContent = eduQuestText.connectionError || 'Connection error. Please try again.';
    errorEl.classList.remove('hidden');
  }
  return false;
}

// ---------- Profile tabs ----------
function switchProfileTab(name) {
  var ach = document.getElementById('tab-ach');
  var bg = document.getElementById('tab-badges');
  if (!ach || !bg) return;
  ach.classList.toggle('active', name === 'ach');
  bg.classList.toggle('active', name === 'badges');
  document.querySelectorAll('.tabs-bar .tab-btn').forEach(function (b, idx) {
    b.classList.toggle('active', (name === 'ach' && idx === 0) || (name === 'badges' && idx === 1));
  });
}

// ---------- Comment likes ----------
async function toggleLike(btn, commentId) {
  try {
    var res = await fetch('/comment/' + commentId + '/like', { method: 'POST' });
    if (res.status === 302 || res.redirected) {
      openAuthModal('login');
      return;
    }
    var json = await res.json();
    if (json.ok) {
      // Update like count and style
      var likeSpan = btn.querySelector('.like-count');
      if (likeSpan) likeSpan.textContent = json.likes;
      btn.style.color = json.liked ? 'var(--primary)' : '';

      // Update dislike button if mutual exclusion occurred
      var commentItem = btn.closest('.comment-actions');
      if (commentItem && json.removed_dislike) {
        var dislikeBtn = commentItem.querySelector('[onclick*="toggleDislike"]');
        if (dislikeBtn) {
          var dislikeSpan = dislikeBtn.querySelector('.dislike-count');
          if (dislikeSpan) dislikeSpan.textContent = json.dislikes;
          dislikeBtn.style.color = '';
        }
      }
    }
  } catch (err) {
    console.warn('like failed', err);
  }
}

// ---------- Comment dislikes ----------
async function toggleDislike(btn, commentId) {
  try {
    var res = await fetch('/comment/' + commentId + '/dislike', { method: 'POST' });
    if (res.status === 302 || res.redirected) {
      openAuthModal('login');
      return;
    }
    var json = await res.json();
    if (json.ok) {
      // Update dislike count and style
      var dislikeSpan = btn.querySelector('.dislike-count');
      if (dislikeSpan) dislikeSpan.textContent = json.dislikes;
      btn.style.color = json.disliked ? 'var(--destructive)' : '';

      // Update like button if mutual exclusion occurred
      var commentItem = btn.closest('.comment-actions');
      if (commentItem && json.removed_like) {
        var likeBtn = commentItem.querySelector('[onclick*="toggleLike"]');
        if (likeBtn) {
          var likeSpan = likeBtn.querySelector('.like-count');
          if (likeSpan) likeSpan.textContent = json.likes;
          likeBtn.style.color = '';
        }
      }
    }
  } catch (err) {
    console.warn('dislike failed', err);
  }
}

// ---------- Auto-hide flash messages ----------
window.addEventListener('load', function () {
  var list = document.getElementById('flash-list');
  if (!list) return;
  setTimeout(function () {
    list.querySelectorAll('.flash').forEach(function (el) {
      el.style.transition = 'opacity 0.4s ease';
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 400);
    });
  }, 4000);
});

// ---------- Notification popup with confetti ----------
function showNotification(type, title, message, icon) {
  // Check if all notifications are disabled or popups are disabled
  if (window.userSettings && (window.userSettings.disableAllNotifications || window.userSettings.disablePopups)) {
    return;
  }

  var popup = document.createElement('div');
  popup.className = 'notification-popup';
  popup.innerHTML = `
    <button class="notif-close" onclick="this.parentElement.remove()">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>
      </svg>
    </button>
    <h3>${title}</h3>
    <p>${message}</p>
    <button class="btn btn-primary" onclick="this.parentElement.remove()">${eduQuestText.notificationOk || 'OK'}</button>
  `;
  document.body.appendChild(popup);

  setTimeout(function () {
    popup.classList.add('show');
  }, 100);

  // Trigger confetti only if enabled
  if (window.userSettings && window.userSettings.enableConfetti) {
    triggerConfetti();
  }

  // Auto-close after 10 seconds
  setTimeout(function () {
    if (popup.parentElement) {
      popup.classList.remove('show');
      setTimeout(function () { popup.remove(); }, 300);
    }
  }, 10000);
}

function triggerConfetti() {
  var canvas = document.getElementById('confetti-canvas');
  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.id = 'confetti-canvas';
    document.body.appendChild(canvas);
  }

  var ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;

  var particles = [];
  var colors = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#ec4899'];

  for (var i = 0; i < 100; i++) {
    particles.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height - canvas.height,
      r: Math.random() * 6 + 2,
      d: Math.random() * 2 + 1,
      color: colors[Math.floor(Math.random() * colors.length)],
      tilt: Math.random() * 10 - 10,
      tiltAngleIncremental: Math.random() * 0.07 + 0.05,
      tiltAngle: 0
    });
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    particles.forEach(function (p, i) {
      ctx.beginPath();
      ctx.lineWidth = p.r / 2;
      ctx.strokeStyle = p.color;
      ctx.moveTo(p.x + p.tilt + p.r, p.y);
      ctx.lineTo(p.x + p.tilt, p.y + p.tilt + p.r);
      ctx.stroke();

      p.tiltAngle += p.tiltAngleIncremental;
      p.y += (Math.cos(p.d) + 3 + p.r / 2) / 2;
      p.x += Math.sin(p.d);
      p.tilt = Math.sin(p.tiltAngle - i / 3) * 15;

      if (p.y > canvas.height) {
        particles.splice(i, 1);
      }
    });

    if (particles.length > 0) {
      requestAnimationFrame(draw);
    } else {
      canvas.remove();
    }
  }

  draw();
}

// Check for notifications from session
window.addEventListener('load', function () {
  // Check if popups are enabled before showing notifications
  var popupsEnabled = window.userSettings && !window.userSettings.disableAllNotifications && !window.userSettings.disablePopups;

  if (popupsEnabled && window.pendingNotifications && window.pendingNotifications.length > 0) {
    window.pendingNotifications.forEach(function (notif) {
      if (notif.type === 'level_up') {
        var levelMessage = (eduQuestText.levelUpMessage || 'Level {level} reached!').replace('{level}', notif.data);
        showNotification('level', eduQuestText.levelUpTitle || 'Level up!', levelMessage);
      } else if (notif.type === 'achievement') {
        showNotification('achievement', eduQuestText.achievementTitle || 'New achievement!', notif.data);
      } else if (notif.type === 'badge') {
        showNotification('badge', eduQuestText.badgeTitle || 'New badge!', notif.data);
      }
    });
  }

  // Always clear notifications from session after checking
  if (window.pendingNotifications && window.pendingNotifications.length > 0) {
    fetch('/clear-notifications', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }
});
