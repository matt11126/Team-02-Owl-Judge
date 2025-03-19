document.addEventListener('DOMContentLoaded', function() {
  /********************************************************
   * HELPER #1: Show notification (success or error)
   ********************************************************/
  function showNotification(message, type = 'success') {
    // Remove any existing notification first
    const existing = document.querySelector('.notification-box');
    if (existing) existing.remove();

    const box = document.createElement('div');
    box.className = 'notification-box';

    // Add checkmark icon for success
    if (type === 'success') {
      const checkmark = document.createElement('span');
      checkmark.innerHTML = '✓ ';
      checkmark.style.fontWeight = 'bold';
      box.appendChild(checkmark);
    }
document.addEventListener('DOMContentLoaded', function() {
  // Helper function to update the header-right section
  function updateAuthButtons(isLoggedIn, username) {
    const headerRight = document.querySelector('.header-right');
    if (!headerRight) return;

    if (isLoggedIn && username) {
      headerRight.innerHTML = `<a href="/logout" class="btn" id="logoutButton">Logout</a>`;
      // Attach logout handler
      const logoutBtn = document.getElementById('logoutButton');
      if (logoutBtn) {
        logoutBtn.addEventListener('click', function(e) {
          e.preventDefault();
          handleLogout();
        });
      }
    } else {
      headerRight.innerHTML = `
        <a href="/login" class="btn">Login</a> |
        <a href="/signup" class="btn">Sign Up</a>
      `;
    }
  }

  // Reuse logout handler from final_auth_overrides.js if available, or define a new one
  function handleLogout() {
    showNotification('Logging out...', 'success'); // From final_auth_overrides.js
    localStorage.removeItem('loggedInUser');
    localStorage.removeItem('loginTimestamp');
    localStorage.removeItem('userRole');
    setTimeout(() => {
      window.location.href = '/logout'; // Server-side logout to clear session
    }, 1500);
  }

  // Check server-side session state (via a hidden element or API)
  function checkSessionState() {
    // Assuming Flask injects current_user into the template
    const isLoggedIn = document.body.dataset.loggedIn === 'true';
    const username = document.body.dataset.username || localStorage.getItem('loggedInUser');
    return { isLoggedIn, username };
  }

  // Sync with client-side state and update UI
  const { isLoggedIn, username } = checkSessionState();
  const clientLoggedIn = !!localStorage.getItem('loggedInUser');

  if (isLoggedIn || clientLoggedIn) {
    updateAuthButtons(true, username || localStorage.getItem('loggedInUser'));
  } else {
    updateAuthButtons(false, null);
  }

  // Listen for manual login/logout updates (e.g., from final_auth_overrides.js)
  window.addEventListener('storage', function(e) {
    if (e.key === 'loggedInUser') {
      const newUsername = e.newValue;
      updateAuthButtons(!!newUsername, newUsername);
    }
  });
});
    // Add message text
    const messageText = document.createElement('span');
    messageText.textContent = message;
    box.appendChild(messageText);

    // Style the notification
    Object.assign(box.style, {
      position: 'fixed',
      top: '10px',
      right: '10px',
      backgroundColor: type === 'success' ? '#4CAF50' : '#f44336',
      color: '#fff',
      padding: '12px 18px',
      borderRadius: '5px',
      fontFamily: 'Arial, sans-serif',
      boxShadow: '0 2px 10px rgba(0,0,0,0.2)',
      zIndex: '999999',
      display: 'flex',
      alignItems: 'center',
      transition: 'opacity 0.3s ease-in-out'
    });

    document.body.appendChild(box);

    // Fade out and remove after 3 seconds
    setTimeout(() => {
      box.style.opacity = '0';
      setTimeout(() => box.remove(), 300);
    }, 3000);
  }

  /********************************************************
   * HELPER #2: Update login state
   ********************************************************/
  function updateLoginState(isLoggedIn, username = null) {
    if (isLoggedIn && username) {
      localStorage.setItem('loggedInUser', username);
      localStorage.setItem('loginTimestamp', Date.now().toString());
      localStorage.setItem('userRole', 'FlaskApp');

      // Update UI to show logged in state
      updateHeaderUI(username);
      injectVotingLink();
    } else {
      // Clear login info
      localStorage.removeItem('loggedInUser');
      localStorage.removeItem('loginTimestamp');
      localStorage.removeItem('userRole');

      // Update UI to show logged out state
      updateHeaderUI(null);
    }
  }

  /********************************************************
   * HELPER #3: Update header UI based on login state
   ********************************************************/
  function updateHeaderUI(username) {
    const headerRight = document.getElementById('loginSignupContainer');
    if (!headerRight) return;

    if (username) {
      // User is logged in
      headerRight.innerHTML = `<span>${username}</span> | <a id="logoutButton" class="btn" href="#">Logout</a>`;

      // Attach event listener to logout button
      const newLogout = document.getElementById('logoutButton');
      if (newLogout) {
        newLogout.addEventListener('click', handleLogout);
      }
    } else {
      // User is logged out
      headerRight.innerHTML = `<a href="/login">Login</a> / <a href="/signup">Sign Up</a>`;
    }
  }

  /********************************************************
   * HELPER #4: Inject voting link for logged in users
   ********************************************************/
  function injectVotingLink() {
    const userName = localStorage.getItem('loggedInUser');
    const navLinks = document.querySelector('ul.nav-links');
    if (userName && navLinks) {
      const alreadyHasVoting = Array.from(navLinks.querySelectorAll('a'))
        .some(a => a.textContent.trim().toLowerCase() === 'voting');
      if (!alreadyHasVoting) {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = '/voting';
        a.textContent = 'Voting';
        li.appendChild(a);
        navLinks.appendChild(li);
      }
    }
  }

  /********************************************************
   * HELPER #5: Handle logout action
   ********************************************************/
  function handleLogout(ev) {
    if (ev) {
      ev.preventDefault();
    }

    // Show logout notification
    showNotification('Logging out...', 'success');

    // Update state
    updateLoginState(false);

    // Redirect to home page
    setTimeout(() => {
      window.location.href = '/';
    }, 1500);
  }

  /********************************************************
   * HELPER #6: Store users in localStorage
   ********************************************************/
  function saveUser(username, password) {
    // Get existing users or initialize empty object
    const users = JSON.parse(localStorage.getItem('users') || '{}');

    // Add or update user
    users[username] = {
      password: password,
      created: Date.now()
    };

    // Save back to localStorage
    localStorage.setItem('users', JSON.stringify(users));
  }

  /********************************************************
   * HELPER #7: Verify user credentials
   ********************************************************/
  function verifyUser(username, password) {
    const users = JSON.parse(localStorage.getItem('users') || '{}');
    return users[username] && users[username].password === password;
  }

  /********************************************************
   * 1) CHECK IF USER IS LOGGED IN
   ********************************************************/
  const username = localStorage.getItem('loggedInUser');
  if (username) {
    updateLoginState(true, username);
  }

  /********************************************************
   * 2) OVERRIDE LOGIN FORM
   ********************************************************/
  const loginForm = document.getElementById('loginForm');
  if (loginForm) {
    loginForm.addEventListener('submit', function(ev) {
      ev.preventDefault();

      const username = document.getElementById('username')?.value || '';
      const password = document.getElementById('password')?.value || '';
      const errElem = document.getElementById('error');

      // Simple validation
      if (!username.trim() || !password.trim()) {
        if (errElem) errElem.textContent = 'Please enter both username and password.';
        return;
      }

      // Show loading state
      const submitBtn = loginForm.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Logging in...';
      }

      // Verify user credentials
      if (verifyUser(username, password)) {
        // Update login state
        updateLoginState(true, username);

        // Show success notification
        showNotification('Logged in successfully!', 'success');

        // Redirect to home page
        setTimeout(() => {
          window.location.href = '/';
        }, 1500);
      } else {
        // Reset button state
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Login';
        }

        // Show error
        if (errElem) errElem.textContent = 'Invalid username or password.';
      }
    });
  }

  /********************************************************
   * 3) OVERRIDE SIGNUP FORM
   ********************************************************/
  const signupForm = document.getElementById('signupForm');
  if (signupForm) {
    signupForm.addEventListener('submit', function(ev) {
      ev.preventDefault();

      const username = document.getElementById('signupUsername')?.value || '';
      const password = document.getElementById('signupPassword')?.value || '';
      const confirm = document.getElementById('signupConfirmPassword')?.value || '';
      const errElem = document.getElementById('signupError');

      // Enhanced validation
      if (!username.trim()) {
        if (errElem) errElem.textContent = 'Please enter a username.';
        return;
      }

      if (!password.trim()) {
        if (errElem) errElem.textContent = 'Please enter a password.';
        return;
      }

      if (password.length < 6) {
        if (errElem) errElem.textContent = 'Password must be at least 6 characters.';
        return;
      }

      if (password !== confirm) {
        if (errElem) errElem.textContent = 'Passwords do not match.';
        return;
      }

      // Show loading state
      const submitBtn = signupForm.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Creating account...';
      }

      // Check if username already exists
      const users = JSON.parse(localStorage.getItem('users') || '{}');
      if (users[username]) {
        if (errElem) errElem.textContent = 'Username already exists.';
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Sign Up';
        }
        return;
      }

      // Save new user
      saveUser(username, password);

      // Update login state
      updateLoginState(true, username);

      // Show success notification
      showNotification('Account created successfully!', 'success');

      // Redirect to home page
      setTimeout(() => {
        window.location.href = '/';
      }, 1500);
    });
  }

  /********************************************************
   * 4) ATTACH LOGOUT HANDLER TO EXISTING BUTTON
   ********************************************************/
  const logoutBtn = document.getElementById('logoutButton');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', handleLogout);
  }
});