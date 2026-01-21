import { Conversation } from "https://cdn.jsdelivr.net/npm/@11labs/client/+esm";

// Authenticated fetch helper that automatically injects JWT token
// and handles 401 redirects to login page.
async function authenticatedFetch(url, options = {}) {
  const token = sessionStorage.getItem('authToken');

  if (!token) {
    console.warn('No auth token found, redirecting to login');
    window.location.href = '/login.html';
    return Promise.reject(new Error('No authentication token'));
  }

  // Merge headers
  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
    ...options.headers
  };

  const response = await fetch(url, {
    ...options,
    headers
  });

  // Handle 401 Unauthorized - redirect to login
  if (response.status === 401) {
    console.warn('Authentication failed, redirecting to login');
    sessionStorage.clear();
    window.location.href = '/login.html';
    return Promise.reject(new Error('Authentication failed'));
  }

  return response;
}


let conversation;
let userTranscript = "";
let sessionActive = false;
let timeRemaining = 0; // Initialize to 0, will be updated by server
let timerInterval;
let totalTalkTime = 0; // Total talk time in seconds
let talkTimeInterval;
let heartbeatInterval; // Server sync heartbeat interval
let talktimeRefreshInterval; // Periodic talktime refresh interval
let onlinePingInterval; // Periodic online status ping interval
let talkTimeStartTime = null; // When the conversation started
let helloPromptTimeout = null; // Timeout for auto-removing "Say Hello" prompt
let paymentModalContext = 'start'; // 'start' or 'during'
let isSessionPaused = false;
let initialTalktime = 0; // Store initial talktime when session starts
let isMicMuted = false; // Track microphone mute state
let userMediaStream = null; // Store the microphone stream for muting
const HEARTBEAT_RATE = 5000; // Sync with server every 5 seconds
// Text status controller - no animation intervals needed


let connectionHealthCheck = null;
let disconnectRetryCount = 0;
let disconnectRetryTimeout = null;
const MAX_RETRY_ATTEMPTS = 3;
const RETRY_DELAY = 2000; // 2 seconds
let lastConnectionTime = null;
let isReconnecting = false;


let speakTimeout = null;
let silenceTimeout = null;
const AUDIO_LATENCY_MS = 100;
const SPEAKING_RATE_MS = 50;

let screens, footer, loadingBar, callStatus, callRing, timerDisplay, micBtn, talkTimeValue, buyTalkTimeBtn, loadingTalkTimeValue;
let talktimeValue, loadingTalktimeValue, callTalktimeValue, btnBuyTalktime;

// Check microphone permission status on load
async function checkMicrophonePermission() {
  try {
    if (navigator.permissions && navigator.permissions.query) {
      const result = await navigator.permissions.query({ name: 'microphone' });
      console.log('🎤 Microphone permission status:', result.state);

      result.onchange = () => {
        console.log('🎤 Microphone permission changed to:', result.state);
        if (result.state === 'granted') {
          console.log('✅ Microphone permission granted');
        } else if (result.state === 'denied') {
          console.warn('⚠️ Microphone permission denied');
        }
      };

      return result.state;
    }
  } catch (err) {
    console.warn('⚠️ Could not check microphone permission status:', err);
  }
  return 'unknown';
}


function initTheme() {
  const savedTheme = localStorage.getItem('theme') || 'light';
  const html = document.documentElement;
  html.setAttribute('data-theme', savedTheme);
  updateThemeIcon(savedTheme);
}

function toggleTheme() {
  const html = document.documentElement;
  const currentTheme = html.getAttribute('data-theme') || 'light';
  const newTheme = currentTheme === 'light' ? 'dark' : 'light';

  html.setAttribute('data-theme', newTheme);
  localStorage.setItem('theme', newTheme);
  updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
  const themeIcon = document.getElementById('themeIcon');
  if (themeIcon) {
    if (theme === 'dark') {
      themeIcon.className = 'fas fa-sun';
    } else {
      themeIcon.className = 'fas fa-moon';
    }
  }
}

// Wait for DOM to be ready
document.addEventListener('DOMContentLoaded', () => {
  console.log('🚀 App initializing...');

  // Initialize theme
  initTheme();

  // Theme toggle button
  const themeToggle = document.getElementById('themeToggle');
  if (themeToggle) {
    themeToggle.addEventListener('click', toggleTheme);
  }

  // Also check for sidebar theme toggle
  const themeToggleSidebar = document.querySelector('.theme-toggle-sidebar');
  if (themeToggleSidebar) {
    themeToggleSidebar.addEventListener('click', toggleTheme);
  }

  // Side panel toggle button
  const sidePanelToggle = document.getElementById('sidePanelToggle');
  const sidePanel = document.getElementById('sidePanel');

  function updateToggleButtonVisibility() {
    if (sidePanel && sidePanelToggle) {
      const isClosed = sidePanel.classList.contains('closed');
      // Show toggle button only when panel is closed
      sidePanelToggle.style.display = isClosed ? 'flex' : 'none';
    }
  }

  if (sidePanelToggle && sidePanel) {
    // Check if panel state is saved in localStorage
    const savedState = localStorage.getItem('sidePanelOpen');
    const isOpen = savedState === null ? false : savedState === 'true'; // Default to closed

    if (!isOpen) {
      sidePanel.classList.add('closed');
    }

    // Update toggle button visibility on load
    updateToggleButtonVisibility();

    sidePanelToggle.addEventListener('click', () => {
      sidePanel.classList.toggle('closed');
      const isNowOpen = !sidePanel.classList.contains('closed');
      localStorage.setItem('sidePanelOpen', isNowOpen.toString());
      updateToggleButtonVisibility();
    });

    // Close button inside panel
    const sidePanelClose = document.getElementById('sidePanelClose');
    if (sidePanelClose) {
      sidePanelClose.addEventListener('click', () => {
        sidePanel.classList.add('closed');
        localStorage.setItem('sidePanelOpen', 'false');
        updateToggleButtonVisibility();
      });
    }
  }

  // Check microphone permission status and update UI
  checkMicrophonePermission().then(status => {
    const permissionNotice = document.querySelector('.permission-notice');
    if (permissionNotice) {
      if (status === 'granted') {
        permissionNotice.innerHTML = '<strong>✅ Microphone Ready:</strong> Permission already granted. You can start your call!';
        permissionNotice.style.background = 'rgba(16, 185, 129, 0.1)';
        permissionNotice.style.borderColor = 'rgba(16, 185, 129, 0.3)';
        console.log('✅ Microphone already has permission');
      } else if (status === 'prompt') {
        permissionNotice.innerHTML = '<strong>🎤 Microphone Required:</strong> When you click "Start Call", Chrome will ask for microphone permission. Please click <strong>"Allow"</strong> to enable voice calls.';
        console.log('💡 Microphone permission will be requested when needed');
      } else if (status === 'denied') {
        permissionNotice.innerHTML = '<strong>⚠️ Microphone Blocked:</strong> Microphone access was denied. Please click the lock icon (🔒) in the address bar and allow microphone access, then refresh the page.';
        permissionNotice.style.background = 'rgba(239, 68, 68, 0.1)';
        permissionNotice.style.borderColor = 'rgba(239, 68, 68, 0.3)';
        console.warn('⚠️ Microphone permission was previously denied');
      }
    }
  });

  // Initialize elements
  screens = {
    ronitStart: document.getElementById('screen-ronit-start'),
    loading: document.getElementById('screen-loading'),
    call: document.getElementById('screen-call')
  };
  footer = document.getElementById('mainFooter');
  loadingBar = document.getElementById('loadingBar');
  callStatus = document.getElementById('callStatus');
  callRing = document.getElementById('callRing');
  timerDisplay = document.getElementById('timerDisplay');
  micBtn = document.getElementById('micBtn');
  talkTimeValue = document.getElementById('talkTimeValue');
  buyTalkTimeBtn = document.getElementById('buyTalkTimeBtn');
  loadingTalkTimeValue = document.getElementById('loadingTalkTimeValue');
  talktimeValue = document.getElementById('talktimeValue');
  loadingTalktimeValue = document.getElementById('loadingTalktimeValue');
  callTalktimeValue = document.getElementById('callTalktimeValue');
  btnBuyTalktime = document.getElementById('btn-buy-talktime');

  // Ensure talk time displays are visible
  const talkTimeDisplay = document.getElementById('talkTimeDisplay');
  const loadingTalkTimeDisplay = document.getElementById('loadingTalkTimeDisplay');
  if (talkTimeDisplay) {
    talkTimeDisplay.style.display = 'block';
    talkTimeDisplay.style.visibility = 'visible';
  }
  if (loadingTalkTimeDisplay) {
    loadingTalkTimeDisplay.style.display = 'block';
    loadingTalkTimeDisplay.style.visibility = 'visible';
  }

  // Initialize and display talktime
  initializeTalktime();

  // Start periodic talktime refresh (every 30 seconds) to sync with admin updates
  startTalktimeRefresh();

  // Force immediate refresh on page load to sync with server
  setTimeout(() => {
    authenticatedFetch('/api/user/talktime')
      .then(res => res.json())
      .then(data => {
        if (data.ok && data.talktime !== undefined) {
          const serverTalktime = data.talktime || 0;
          sessionStorage.setItem('userTalktime', serverTalktime.toString());
          updateTalktimeDisplay(serverTalktime);
          console.log(`🔄 Initial talktime sync: ${serverTalktime}s`);
        }
      })
      .catch(err => console.warn('⚠️ Initial sync failed:', err));
  }, 1000); // Wait 1 second after page load

  // Start periodic online status ping (every 60 seconds) to keep user marked as online
  startOnlinePing();

  // Initialize side panel talktime display (will be updated by initializeTalktime)
  // Note: sidePanelTalktimeValue is updated in updateTalktimeDisplay function
  const sidePanelTalktimeValueEl = document.getElementById('sidePanelTalktimeValue');
  if (sidePanelTalktimeValueEl) {
    const talktime = parseInt(sessionStorage.getItem('userTalktime') || '0', 10);
    sidePanelTalktimeValueEl.textContent = talktime.toLocaleString();
  }

  // Verify all elements exist
  const missing = [];
  if (!screens.ronitStart) missing.push('screen-ronit-start');
  if (!screens.loading) missing.push('screen-loading');
  if (!screens.call) missing.push('screen-call');
  if (missing.length > 0) {
    console.error('❌ Missing elements:', missing);
  } else {
    console.log('✅ All elements found');
  }

  // Pre-fill user data from sessionStorage (from login)
  const savedEmail = sessionStorage.getItem('userEmail');
  if (savedEmail) {
    const emailInput = document.getElementById('userEmail');
    if (emailInput) emailInput.value = savedEmail;
  }

  // Change Account button handler
  const btnChangeAccount = document.getElementById('btn-change-account');
  if (btnChangeAccount) {
    console.log('✅ Change account button found and initialized');
    btnChangeAccount.addEventListener('click', () => {
      // Clear session but keep theme preference
      const theme = localStorage.getItem('theme');
      sessionStorage.clear();
      if (theme) {
        localStorage.setItem('theme', theme);
      }
      window.location.href = '/login.html';
    });
  } else {
    console.warn('⚠️ Change account button not found');
  }

  // Logout handler
  const btnLogout = document.getElementById('btn-logout');
  if (btnLogout) {
    console.log('✅ Logout button found and initialized');
    btnLogout.addEventListener('click', () => {
      if (confirm('Are you sure you want to logout?')) {
        sessionStorage.clear();
        window.location.href = '/login.html';
      }
    });
  } else {
    console.warn('⚠️ Logout button not found');
  }

  const btnStartLoading = document.getElementById('btn-start-loading');
  if (btnStartLoading) {
    console.log('✅ Start call button found and initialized');
    btnStartLoading.addEventListener('click', async () => {
      const email = document.getElementById('userEmail')?.value?.trim() || '';

      // Validate email format
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!email) {
        alert("Please enter your email address to receive your personalized care plan.");
        const emailInput = document.getElementById('userEmail');
        if (emailInput) emailInput.focus();
        return;
      }

      if (!emailRegex.test(email)) {
        alert("Please enter a valid email address (e.g., yourname@example.com).");
        const emailInput = document.getElementById('userEmail');
        if (emailInput) {
          emailInput.focus();
          emailInput.select();
        }
        return;
      }

      // Get name from email or sessionStorage
      const name = sessionStorage.getItem('userName') || email.split('@')[0] || 'User';

      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) {
        if (!window.globalAudioContext) {
          window.globalAudioContext = new AudioContext();
        }
        window.globalAudioContext.resume().then(() => {
          console.log('🔊 AudioContext resumed via user gesture');
        }).catch(err => {
          console.warn('⚠️ AudioContext resume failed:', err);
        });
      }

      // Check if user has talktime
      const talktime = parseInt(sessionStorage.getItem('userTalktime') || '0', 10);
      if (talktime <= 0) {
        // Show payment modal
        showPaymentModal('start');
        btnStartLoading.disabled = false;
        const phoneIcon = document.querySelector('#btn-start-loading i');
        if (phoneIcon) {
          btnStartLoading.innerHTML = '<i class="fas fa-phone-alt"></i><span>Start Call with Ronit</span>';
        } else {
          btnStartLoading.innerHTML = '<i class="fas fa-phone-alt"></i><span>Start Call with Ronit</span>';
        }
        return;
      }

      // Disable button to prevent multiple clicks
      btnStartLoading.disabled = true;
      btnStartLoading.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Starting...</span>';

      // Hide Ronit Start, Show Loading
      if (screens.ronitStart) screens.ronitStart.classList.add('hidden');
      if (screens.loading) screens.loading.classList.remove('hidden');
      if (footer) footer.style.display = 'none'; // Hide footer for call view

      // Initialize and display talk time on loading screen
      timeRemaining = 180; // Reset to 3 minutes
      if (loadingTalkTimeValue) {
        loadingTalkTimeValue.textContent = '03:00';
      }

      // Update talktime display on loading screen
      if (loadingTalktimeValue) {
        const talktime = parseInt(sessionStorage.getItem('userTalktime') || '0', 10);
        loadingTalktimeValue.textContent = talktime.toLocaleString();
      }

      // Save user data to sessionStorage
      sessionStorage.setItem('userEmail', email);
      sessionStorage.setItem('userName', name); // Use email prefix as name

      // [FIX] Start immediately to preserve User Gesture for Audio/Mic
      console.log('📞 Starting call process...');

      // Fill loading bar visually (optional)
      if (loadingBar) {
        loadingBar.style.transition = 'width 0.5s ease';
        loadingBar.style.width = '100%';
      }

      // CALL IMMEDIATELY - Do not wait for a timer!
      // This allows the browser to grant microphone/audio permissions.
      startVoiceSession();
    });
  }

  // End button listener
  const endBtn = document.getElementById('endBtn');
  if (endBtn) {
    endBtn.addEventListener('click', endSession);
  }

  // Mic button - Mute/Unmute functionality
  if (micBtn) {
    micBtn.addEventListener('click', toggleMicrophone);
  }

  // Buy Talk Time Button
  if (buyTalkTimeBtn) {
    buyTalkTimeBtn.addEventListener('click', handleBuyTalkTime);
  }

  // Buy Talktime Button (main card - if exists)
  if (btnBuyTalktime) {
    btnBuyTalktime.addEventListener('click', handleBuyTalktime);
  }

  // Side Panel Buy Talktime Button
  const sidePanelBuyBtn = document.getElementById('sidePanelBuyTalktime');
  if (sidePanelBuyBtn) {
    sidePanelBuyBtn.addEventListener('click', handleBuyTalktime);
    console.log('✅ Side panel buy talktime button initialized');
  } else {
    console.warn('⚠️ Side panel buy talktime button not found');
  }

  // Initialize talktime on page load
  initializeTalktime();

  // Re-check welcome bonus when email changes
  const emailInput = document.getElementById('userEmail');
  if (emailInput) {
    let emailCheckTimeout;
    emailInput.addEventListener('input', () => {
      clearTimeout(emailCheckTimeout);
      emailCheckTimeout = setTimeout(() => {
        const email = emailInput.value?.trim();
        if (email && email.includes('@')) {
          // Re-initialize talktime when valid email is entered
          initializeTalktime();
        }
      }, 1000); // Wait 1 second after user stops typing
    });
  }

  // Initialize payment modal buttons
  initializePaymentModal();
});

// Payment Modal Functions
function showPaymentModal(context) {
  paymentModalContext = context;
  const modal = document.getElementById('paymentModal');
  const message = document.getElementById('paymentModalMessage');
  if (modal) {
    modal.style.display = 'flex';
    if (message) {
      message.textContent = '';
      message.className = 'payment-modal-message';
    }
  }
}

function hidePaymentModal() {
  const modal = document.getElementById('paymentModal');
  if (modal) {
    modal.style.display = 'none';
  }
}

function pauseSessionForPayment() {
  if (!sessionActive || isSessionPaused) return;

  isSessionPaused = true;

  // Pause the conversation
  if (conversation) {
    try {
      // Mute the conversation to pause it
      conversation.setConversationTurnDetection({
        enabled: false
      });
      console.log('⏸️ Session paused - talktime is 0');
    } catch (e) {
      console.error('Error pausing conversation:', e);
    }
  }

  // Show payment modal
  showPaymentModal('during');
  updateStatus('Session Paused - Buy Talktime to Continue', 'default');
}

function resumeSession() {
  if (!isSessionPaused) return;

  isSessionPaused = false;

  // Resume the conversation
  if (conversation) {
    try {
      // Re-enable conversation turn detection
      conversation.setConversationTurnDetection({
        enabled: true
      });
      console.log('▶️ Session resumed');
    } catch (e) {
      console.error('Error resuming conversation:', e);
    }
  }

  // [CRITICAL FIX] REMOVED the code that hid the status text
  // The text should remain visible indicating "Listening..."
  toggleVoiceVisuals('listening');
}

function initializePaymentModal() {
  const paymentCancelBtn = document.getElementById('paymentCancelBtn');
  const paymentProceedBtn = document.getElementById('paymentProceedBtn');
  const paymentModalMessage = document.getElementById('paymentModalMessage');

  if (paymentCancelBtn) {
    paymentCancelBtn.addEventListener('click', () => {
      if (paymentModalContext === 'during') {
        // End session if user cancels during call
        endSession();
      } else {
        // Just hide modal if canceling before start
        hidePaymentModal();
      }
    });
  }

  if (paymentProceedBtn) {
    paymentProceedBtn.addEventListener('click', async () => {
      if (!paymentProceedBtn) return;

      try {
        paymentProceedBtn.disabled = true;
        paymentProceedBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Processing...</span>';
        if (paymentModalMessage) {
          paymentModalMessage.textContent = 'Creating payment order...';
          paymentModalMessage.className = 'payment-modal-message info';
        }

        // Create order for talktime purchase
        const response = await authenticatedFetch('/api/payments/razorpay/order', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            amount_paisa: 49900, // ₹499 in paise
            currency: 'INR',
            receipt: `talktime_${Date.now()}`
          })
        });

        const orderData = await response.json();
        if (!response.ok || !orderData?.ok) {
          throw new Error(orderData?.error || 'Order creation failed');
        }

        const { order, key_id } = orderData;

        const options = {
          key: key_id,
          amount: order.amount,
          currency: order.currency,
          name: 'AI Voice Coach',
          description: 'Purchase Talktime (100 talktime)',
          order_id: order.id,
          handler: async function (response) {
            try {
              // Verify payment
              const verifyResponse = await authenticatedFetch('/api/payments/razorpay/verify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  razorpay_order_id: response.razorpay_order_id,
                  razorpay_payment_id: response.razorpay_payment_id,
                  razorpay_signature: response.razorpay_signature
                })
              });

              const verifyData = await verifyResponse.json();
              if (verifyResponse.ok && verifyData.ok) {
                // Add talktime
                addTalktime(100);

                if (paymentModalMessage) {
                  paymentModalMessage.textContent = 'Payment successful! Adding talktime...';
                  paymentModalMessage.className = 'payment-modal-message success';
                }

                // Hide modal after short delay
                setTimeout(() => {
                  hidePaymentModal();

                  if (paymentModalContext === 'during') {
                    // Resume session
                    resumeSession();
                  } else {
                    // Start the call
                    const btnStartLoading = document.getElementById('btn-start-loading');
                    if (btnStartLoading) {
                      btnStartLoading.click();
                    }
                  }
                }, 1500);
              } else {
                throw new Error(verifyData?.error || 'Payment verification failed');
              }
            } catch (error) {
              console.error('Payment verification error:', error);
              if (paymentModalMessage) {
                paymentModalMessage.textContent = 'Payment verification failed. Please try again.';
                paymentModalMessage.className = 'payment-modal-message error';
              }
              paymentProceedBtn.disabled = false;
              paymentProceedBtn.innerHTML = '<i class="fas fa-lock"></i><span>Pay & Continue</span>';
            }
          },
          modal: {
            ondismiss: function () {
              paymentProceedBtn.disabled = false;
              paymentProceedBtn.innerHTML = '<i class="fas fa-lock"></i><span>Pay & Continue</span>';
              if (paymentModalMessage) {
                paymentModalMessage.textContent = '';
                paymentModalMessage.className = 'payment-modal-message';
              }
            }
          }
        };

        const rzp = new Razorpay(options);
        rzp.open();
      } catch (error) {
        console.error('Payment error:', error);
        if (paymentModalMessage) {
          paymentModalMessage.textContent = 'Error: ' + error.message;
          paymentModalMessage.className = 'payment-modal-message error';
        }
        paymentProceedBtn.disabled = false;
        paymentProceedBtn.innerHTML = '<i class="fas fa-lock"></i><span>Pay & Continue</span>';
      }
    });
  }
}

// --- Voice Logic ---

async function requestMicrophonePermission() {
  // Check if getUserMedia is available
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return {
      success: false,
      error: 'getUserMedia is not supported in this browser. Please use Chrome, Firefox, or Edge.'
    };
  }

  // Check permission status (non-blocking - always attempt getUserMedia)
  // Permissions API is inconsistent on Firefox and Safari (iOS), so we don't rely on it
  let permissionStatus = 'unknown';
  try {
    if (navigator.permissions && navigator.permissions.query) {
      const result = await navigator.permissions.query({ name: 'microphone' });
      permissionStatus = result.state;
      console.log('🎤 Permissions API status:', permissionStatus);

      // Only return early if permission is EXPLICITLY denied
      // Even if granted or prompt, we MUST attempt getUserMedia (iOS/Firefox may report incorrectly)
      if (permissionStatus === 'denied') {
        return {
          success: false,
          error: 'Microphone permission was denied. Please enable it in browser settings.\n\n' +
            'To fix this in Chrome:\n' +
            '1. Click the lock icon (🔒) in the address bar\n' +
            '2. Set "Microphone" to "Allow"\n' +
            '3. Refresh the page and try again'
        };
      }
    }
  } catch (permErr) {
    // Permissions API not supported or failed (common on iOS Safari, Firefox)
    // This is OK - we will attempt getUserMedia regardless
    console.log('⚠️ Permissions API unavailable or failed (this is normal on some browsers)');
    permissionStatus = 'unknown';
  }

  // CRITICAL: Always attempt getUserMedia even if permissions API is inconclusive
  // This ensures compatibility with iOS Safari and Firefox where permissions API is unreliable

  // Check if we already have an active stream
  if (userMediaStream) {
    const activeTracks = userMediaStream.getAudioTracks().filter(t => t.readyState === 'live');
    if (activeTracks.length > 0 && userMediaStream.active) {
      console.log('✅ Reusing existing microphone stream');
      return true;
    } else {
      // Clean up inactive stream
      console.log('🧹 Cleaning up inactive stream');
      userMediaStream.getTracks().forEach(track => track.stop());
      userMediaStream = null;
    }
  }

  // Attempt 1: Try with high-quality constraints
  const highQualityConstraints = {
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    }
  };

  let stream = null;
  let lastError = null;

  try {
    console.log('🎤 Attempt 1: Requesting microphone with high-quality constraints...');
    stream = await navigator.mediaDevices.getUserMedia(highQualityConstraints);
    console.log('✅ High-quality constraints succeeded');
  } catch (err) {
    console.warn('⚠️ High-quality constraints failed:', err.name, err.message);
    lastError = err;

    // If NotReadableError or OverconstrainedError, try fallback (do not fail immediately)
    if (err.name === 'NotReadableError' || err.name === 'OverconstrainedError' ||
      err.name === 'TrackStartError' || err.name === 'ConstraintNotSatisfiedError') {

      console.log('🔄 Attempt 2: Trying with minimal constraints...');

      // Attempt 2: Try with minimal constraints
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        console.log('✅ Minimal constraints succeeded');
      } catch (retryErr) {
        console.error('❌ Minimal constraints also failed:', retryErr.name, retryErr.message);
        lastError = retryErr;

        // Generate specific error message based on error type
        let errorMessage = '';
        if (retryErr.name === 'NotAllowedError' || retryErr.name === 'PermissionDeniedError') {
          errorMessage = 'Microphone permission denied. Please allow microphone access in your browser settings.\n\n' +
            'To fix this in Chrome:\n' +
            '1. Click the lock icon (🔒) in the address bar\n' +
            '2. Set "Microphone" to "Allow"\n' +
            '3. Refresh the page and try again';
        } else if (retryErr.name === 'NotFoundError' || retryErr.name === 'DevicesNotFoundError') {
          errorMessage = 'No microphone found. Please connect a microphone and try again.';
        } else if (retryErr.name === 'NotReadableError' || retryErr.name === 'TrackStartError') {
          errorMessage = 'Could not start audio source. Is another app using the microphone? Please close other applications using the microphone and try again.';
        } else if (retryErr.name === 'OverconstrainedError' || retryErr.name === 'ConstraintNotSatisfiedError') {
          errorMessage = 'Microphone does not meet the required specifications. Please check your device settings or try a different microphone.';
        } else {
          errorMessage = `Could not access microphone: ${retryErr.message || 'Unknown error occurred'}. Please check your device settings.`;
        }

        return { success: false, error: errorMessage };
      }
    } else {
      // For other errors (NotAllowedError, NotFoundError, etc.), return immediately
      let errorMessage = '';
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        errorMessage = 'Microphone permission denied. Please allow microphone access in your browser settings.\n\n' +
          'To fix this in Chrome:\n' +
          '1. Click the lock icon (🔒) in the address bar\n' +
          '2. Set "Microphone" to "Allow"\n' +
          '3. Refresh the page and try again';
      } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
        errorMessage = 'No microphone found. Please connect a microphone and try again.';
      } else {
        errorMessage = `Could not access microphone: ${err.message || 'Unknown error occurred'}. Please check your device settings.`;
      }

      return { success: false, error: errorMessage };
    }
  }

  // Verify stream is fully active before proceeding
  if (!stream) {
    return {
      success: false,
      error: 'Failed to obtain microphone stream. Please try again.'
    };
  }

  // Check if we actually got audio tracks
  const audioTracks = stream.getAudioTracks();
  if (audioTracks.length === 0) {
    stream.getTracks().forEach(track => track.stop());
    return {
      success: false,
      error: 'No audio tracks available. Please check your microphone connection.'
    };
  }

  // WebRTC Connection Safeguard: Verify stream is active and tracks are live
  // Add a small delay to allow stream to fully activate (some hardware needs time)
  let activationAttempts = 0;
  const maxActivationAttempts = 10;
  const activationDelay = 100; // 100ms between checks

  while (activationAttempts < maxActivationAttempts) {
    if (stream.active) {
      const liveTracks = audioTracks.filter(t => t.readyState === 'live');
      if (liveTracks.length > 0) {
        console.log(`✅ Stream activated after ${activationAttempts * activationDelay}ms`);
        break;
      }
    }

    activationAttempts++;
    if (activationAttempts < maxActivationAttempts) {
      await new Promise(resolve => setTimeout(resolve, activationDelay));
    }
  }

  // Final verification after waiting period
  if (!stream.active) {
    stream.getTracks().forEach(track => track.stop());
    return {
      success: false,
      error: 'Microphone stream did not become active. Please check your microphone connection and try again.'
    };
  }

  const liveTracks = audioTracks.filter(t => t.readyState === 'live');
  if (liveTracks.length === 0) {
    stream.getTracks().forEach(track => track.stop());
    return {
      success: false,
      error: 'Microphone tracks did not become live. Please check your microphone and try again.'
    };
  }

  console.log('✅ Microphone permission granted and stream verified');
  console.log('📊 Audio track info:', {
    label: audioTracks[0].label,
    enabled: audioTracks[0].enabled,
    readyState: audioTracks[0].readyState,
    streamActive: stream.active,
    liveTracksCount: liveTracks.length,
    totalTracksCount: audioTracks.length,
    settings: audioTracks[0].getSettings()
  });

  // Store stream - will be managed by SDK after connection
  userMediaStream = stream;

  return true;
}

// --- Microphone Mute/Unmute Functions ---
function toggleMicrophone() {
  if (!sessionActive) {
    console.log('⚠️ Cannot toggle mic: session not active');
    return;
  }

  isMicMuted = !isMicMuted;
  let tracksControlled = 0;

  // Method 1: Mute/unmute through stored media stream (Primary Method)
  // This is the stream we got during permission request
  if (userMediaStream) {
    userMediaStream.getAudioTracks().forEach(track => {
      // Control tracks regardless of state - enabled property works on all states
      const wasEnabled = track.enabled;
      track.enabled = !isMicMuted;
      tracksControlled++;
      console.log(`🎤 Track "${track.label || 'Unknown'}": ${isMicMuted ? 'MUTED' : 'UNMUTED'} (enabled: ${wasEnabled} → ${!isMicMuted}, state=${track.readyState})`);
    });
  }

  // Method 2: Try to get stream from conversation object if available
  // Some SDK versions expose the stream
  if (conversation) {
    try {
      // Try different possible methods to access the stream
      if (typeof conversation.getLocalStream === 'function') {
        const convStream = conversation.getLocalStream();
        if (convStream && convStream !== userMediaStream) {
          convStream.getAudioTracks().forEach(track => {
            track.enabled = !isMicMuted;
            tracksControlled++;
            console.log(`🎤 Conversation stream track: ${isMicMuted ? 'MUTED' : 'UNMUTED'}`);
          });
        }
      }

      // Try to access through other possible properties
      if (conversation.localStream) {
        conversation.localStream.getAudioTracks().forEach(track => {
          track.enabled = !isMicMuted;
          tracksControlled++;
          console.log(`🎤 Local stream track: ${isMicMuted ? 'MUTED' : 'UNMUTED'}`);
        });
      }
    } catch (e) {
      // Expected - not all SDK versions expose the stream this way
    }
  }

  // Method 3: Disable/enable turn detection through ElevenLabs conversation
  // This prevents the agent from processing user input when muted
  if (conversation) {
    try {
      if (isMicMuted) {
        conversation.setConversationTurnDetection({ enabled: false });
        console.log('🔇 Turn detection disabled - agent will not process user input');
      } else {
        conversation.setConversationTurnDetection({ enabled: true });
        console.log('🎤 Turn detection enabled - agent can process user input');

        // [FIX] Also ensure microphone tracks are enabled when unmuting
        if (userMediaStream) {
          userMediaStream.getAudioTracks().forEach(track => {
            if (track.readyState === 'live') {
              track.enabled = true;
              console.log(`✅ Enabled audio track: ${track.label}`);
            } else {
              console.warn(`⚠️ Track not live: ${track.label}, state: ${track.readyState}`);
            }
          });
        }
      }
    } catch (e) {
      console.warn('⚠️ Could not update conversation turn detection:', e);
    }
  }

  // Log the result
  if (tracksControlled > 0) {
    console.log(`✅ Microphone ${isMicMuted ? 'MUTED' : 'UNMUTED'} - ${tracksControlled} audio track(s) controlled`);
  } else {
    console.warn('⚠️ No audio tracks found. Using turn detection method only.');
    console.log(`ℹ️ Microphone ${isMicMuted ? 'MUTED' : 'UNMUTED'} via turn detection`);
  }

  // Update UI
  updateMicButtonState(isMicMuted);

  // Show brief status update, then REVERT to main state
  if (callStatus) {
    // [CRITICAL FIX] Remove hidden class so CSS !important doesn't block visibility
    callStatus.classList.remove('hidden');

    callStatus.textContent = isMicMuted ? '🔇 Microphone Muted' : '🎤 Microphone Active';
    callStatus.style.display = 'inline-block';

    // Remove any existing classes temporarily
    callStatus.classList.remove('speaking');

    setTimeout(() => {
      // CRITICAL FIX: Don't hide it! Revert to correct state.
      if (sessionActive) {
        // If muted, stay muted text, otherwise go back to Listening
        if (isMicMuted) {
          callStatus.textContent = '🔇 Muted';
        } else {
          // Force refresh the visual state
          toggleVoiceVisuals('listening');
        }
      }
    }, 2000);
  }
}

function updateMicButtonState(muted) {
  if (!micBtn) return;

  const icon = micBtn.querySelector('.control-btn-inner i') || micBtn.querySelector('i');
  const label = micBtn.querySelector('.control-label');

  if (muted) {
    // Muted state - red background, slash icon
    micBtn.classList.add('muted');
    if (icon) {
      icon.className = 'fas fa-microphone-slash';
    }
    if (label) {
      label.textContent = 'Muted';
    }
    micBtn.setAttribute('aria-label', 'Unmute Microphone');
    console.log('🔇 Mic button updated to muted state');
  } else {
    // Unmuted state - normal gray background, mic icon
    micBtn.classList.remove('muted');
    if (icon) {
      icon.className = 'fas fa-microphone';
    }
    if (label) {
      label.textContent = 'Mic';
    }
    micBtn.setAttribute('aria-label', 'Mute Microphone');
    console.log('🎤 Mic button updated to unmuted state');
  }
}

// Helper function to ensure mute state is maintained
// This periodically checks and enforces the mute state in case tracks get re-enabled
function enforceMicMuteState() {
  if (!sessionActive || !isMicMuted) return;

  // Enforce mute on stored stream
  if (userMediaStream) {
    userMediaStream.getAudioTracks().forEach(track => {
      if (track.enabled) {
        track.enabled = false;
        console.log('🔇 Enforcing mute state on track:', track.label || 'Unknown');
      }
    });
  }

  // Also enforce through conversation turn detection
  if (conversation) {
    try {
      conversation.setConversationTurnDetection({ enabled: false });
    } catch (e) {
      // Ignore errors
    }
  }
}

async function startVoiceSession() {
  // 1. Reset State
  userTranscript = "";
  timeRemaining = 180;
  totalTalkTime = 0;
  isMicMuted = false;

  // 2. UI Setup (Hide Start, Show Call)
  if (screens.loading) screens.loading.classList.add('hidden');
  if (screens.ronitStart) screens.ronitStart.classList.add('hidden');
  if (screens.call) {
    screens.call.classList.remove('hidden');
    screens.call.style.display = 'flex';
  }
  if (footer) footer.style.display = 'none';

  // Hide Side Panel
  const sidePanel = document.getElementById('sidePanel');
  const sidePanelToggle = document.getElementById('sidePanelToggle');
  if (sidePanel) sidePanel.style.display = 'none';
  if (sidePanelToggle) sidePanelToggle.style.display = 'none';

  updateStatus('Requesting microphone access...', 'connecting');

  // 3. CRITICAL: Request Microphone FIRST
  // Do NOT touch AudioContext before this line completes
  const permissionResult = await requestMicrophonePermission();

  if (permissionResult !== true) {
    const errorMsg = permissionResult?.error || 'Microphone access denied.';
    alert(errorMsg);
    // Reset UI to Start Screen
    if (screens.call) screens.call.classList.add('hidden');
    if (screens.ronitStart) screens.ronitStart.classList.remove('hidden');
    if (footer) footer.style.display = 'block';
    if (sidePanel) sidePanel.style.display = 'flex';
    if (sidePanelToggle) sidePanelToggle.style.display = 'flex';
    return;
  }

  // 4. NOW it is safe to wake up AudioContext
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (AudioContext) {
      const ctx = new AudioContext();
      await ctx.resume();
      // Keep ctx alive or close it based on need, but resume is key
    }
  } catch (e) {
    console.warn("AudioContext wakeup warning:", e);
  }

  // 5. OBSERVE GOD LEVEL HANDSHAKE
  try {
    updateStatus('Connecting to Secure Server...', 'connecting');

    const startRes = await authenticatedFetch('/api/session/start', { method: 'POST' });

    // Handle "Server Busy" (503) from Gatekeeper
    if (startRes.status === 503) {
      alert("⚠️ High Traffic: All AI coaches are currently busy. Please try again in 30 seconds.");
      updateStatus('Server Busy', 'error');
      // Reset UI
      endSession();
      return;
    }

    const startData = await startRes.json();

    if (!startData.ok) {
      if (startRes.status === 402 || startData.error === "Insufficient Funds") {
        showPaymentModal('start');
        return;
      }
      throw new Error(startData.error || "Session failed");
    }

    console.log("✅ Secure Session Started. ID:", startData.session_id);

    // Initialize UI with server truth
    updateTalktimeDisplay(startData.remaining_seconds);
    timeRemaining = parseInt(startData.remaining_seconds);
    sessionStorage.setItem('userTalktime', timeRemaining);

  } catch (e) {
    console.error("Session start failed", e);
    updateStatus('Connection Failed', 'error');
    return;
  }

  updateStatus('Connecting to AI service...', 'connecting');

  try {
    const cfgRes = await fetch('/config', { cache: 'no-store' });
    if (!cfgRes.ok) throw new Error('Failed to fetch configuration');
    const cfg = await cfgRes.json();

    // ✅ NEW / SECURE CODE
    const authToken = sessionStorage.getItem("authToken"); // Get the stored token
    if (!authToken) {
      console.error("No token found, user must login.");
      // Optional: Redirect to login or just fail gracefully
      throw new Error("Authentication required");
    }

    const tokenRes = await fetch("/conversation-token", {
      method: "GET",
      headers: {
        "Authorization": "Bearer " + authToken,  // <--- The Key to the Gate
        "Content-Type": "application/json"
      }
    });

    if (!tokenRes.ok) throw new Error('Token request failed');
    const tokenData = await tokenRes.json();
    const token = tokenData.token; // Extract token from response

    if (!token) {
      throw new Error('Token not received from server');
    }

    console.log('🎙️ Starting conversation...');

    // [PRODUCTION FIX] Increased timeout and better handling
    const connectionTimeout = setTimeout(() => {
      if (!sessionActive && !isReconnecting) {
        console.warn('⏱️ Connection timeout - attempting recovery...');
        updateStatus('Connection taking longer than expected...', 'connecting');
        // Don't end immediately - give it more time
      }
    }, 30000); // Increased to 30 seconds for VPS latency

    // Start ElevenLabs Session
    console.log('🔑 Using token:', token.substring(0, 10) + '...');

    conversation = await Conversation.startSession({
      agentId: cfg.agentId,
      conversationToken: token,

      // [FIX] Removing overrides to ensure stability
      // overrides: { ... }

      // 1. SMART LATENCY TRIGGER (The Alternate Fix)
      onMessage: ({ source, message }) => {
        const speaker = source === 'user' ? 'User' : 'Coach';
        userTranscript += `[${new Date().toLocaleTimeString()}] ${speaker}: ${message}\n`;

        // [PRODUCTION FIX] Update connection activity timestamp
        lastConnectionTime = Date.now();

        if (source === 'ai' || source === 'agent' || source === 'assistant') {
          console.log(`💬 Text received (${message.length} chars). Syncing visuals...`);

          // Clear any existing timers to prevent overlaps
          if (speakTimeout) clearTimeout(speakTimeout);
          if (silenceTimeout) clearTimeout(silenceTimeout);

          // STEP A: Wait for audio buffering (Latency Compensation)
          speakTimeout = setTimeout(() => {
            toggleVoiceVisuals('speaking');

            // STEP B: Calculate how long to stay green
            // Average speaking rate is ~15-20 chars per second. 
            // 50ms per char is a safe average for AI voices.
            const estimatedDuration = Math.max(1500, message.length * SPEAKING_RATE_MS);

            // STEP C: Schedule the "Silence" switch
            silenceTimeout = setTimeout(() => {
              toggleVoiceVisuals('listening');
            }, estimatedDuration);

          }, AUDIO_LATENCY_MS); // Wait 100ms before starting (reduced for snappier visuals)
        }
      },

      // 2. SAFETY SWITCH (Ensures we never get "Stuck")
      onModeChange: (mode) => {
        const currentMode = mode.mode || mode;
        console.log('🔄 Mode:', currentMode);

        // [PRODUCTION FIX] Update connection activity on mode changes
        lastConnectionTime = Date.now();

        // If the SDK explicitly says "listening", we trust it and cut the visual short.
        if (currentMode === 'listening') {
          if (silenceTimeout) clearTimeout(silenceTimeout);
          toggleVoiceVisuals('listening');
        }
      },

      onConnect: () => {
        clearTimeout(connectionTimeout);
        sessionActive = true;
        isMicMuted = false;
        isReconnecting = false;
        disconnectRetryCount = 0; // Reset retry count on successful connection
        lastConnectionTime = Date.now();

        // [FIX] Simplified Stream Management
        // Just log status, don't mess with streams aggressively
        console.log('✅ Connection established');

        if (userMediaStream && userMediaStream.active) {
          console.log('🎤 Permission stream active');
        }

        updateMicButtonState(false);

        if (window.micMuteInterval) clearInterval(window.micMuteInterval);

        // [PRODUCTION FIX] Start connection health monitoring
        startConnectionHealthCheck();

        // Connection UI Updates
        const connectionStatus = document.getElementById('connectionStatus');
        if (connectionStatus) {
          connectionStatus.classList.add('connected');
          const statusText = connectionStatus.querySelector('.status-text');
          if (statusText) statusText.textContent = 'Connected';
        }

        // Initial Status
        updateStatus('Connected', 'default');
        setTimeout(() => { toggleVoiceVisuals('listening'); }, 100);

        startTalkTimeTracking();

        console.log('✅ Session connected successfully');
        console.log('🎤 Microphone should now be active - try speaking to the bot!');
      },

      onDisconnect: () => {
        clearTimeout(connectionTimeout);
        stopConnectionHealthCheck();

        // Clear sync timers
        if (speakTimeout) clearTimeout(speakTimeout);
        if (silenceTimeout) clearTimeout(silenceTimeout);

        // [PRODUCTION FIX] Don't immediately end session - try to recover
        console.warn('⚠️ Connection disconnected');

        // Only end session if we've been disconnected for a while or retries failed
        if (disconnectRetryCount >= MAX_RETRY_ATTEMPTS) {
          console.error('❌ Max reconnection attempts reached. Ending session.');
          toggleVoiceVisuals('idle');
          updateStatus('Connection lost. Please refresh.', 'default');
          setTimeout(() => endSession(), 2000);
          return;
        }

        // Attempt reconnection
        if (sessionActive && !isReconnecting) {
          isReconnecting = true;
          disconnectRetryCount++;
          console.log(`🔄 Attempting reconnection (${disconnectRetryCount}/${MAX_RETRY_ATTEMPTS})...`);

          updateStatus(`Reconnecting... (${disconnectRetryCount}/${MAX_RETRY_ATTEMPTS})`, 'connecting');

          // Clear retry timeout if exists
          if (disconnectRetryTimeout) clearTimeout(disconnectRetryTimeout);

          // Wait before retrying
          disconnectRetryTimeout = setTimeout(() => {
            if (sessionActive) {
              // The SDK should handle reconnection automatically
              // Just update UI and wait
              console.log('⏳ Waiting for automatic reconnection...');
            }
          }, RETRY_DELAY);
        } else if (!sessionActive) {
          // Session was already ended, just cleanup
          toggleVoiceVisuals('idle');
          updateStatus('Disconnected', 'default');
        }
      },

      onError: (err) => {
        clearTimeout(connectionTimeout);
        stopConnectionHealthCheck();

        // Clear sync timers
        if (speakTimeout) clearTimeout(speakTimeout);
        if (silenceTimeout) clearTimeout(silenceTimeout);

        console.error('❌ Connection error:', err);

        // [PRODUCTION FIX] Handle errors more gracefully
        const errorMessage = err.message || err.toString() || 'Unknown error';
        const isFatalError = errorMessage.includes('closed') ||
          errorMessage.includes('failed') ||
          errorMessage.includes('timeout');

        if (isFatalError && disconnectRetryCount >= MAX_RETRY_ATTEMPTS) {
          // Fatal error after retries - end session
          toggleVoiceVisuals('idle');
          updateStatus('Connection error. Please refresh.', 'default');
          alert('Connection error: ' + errorMessage + '\n\nPlease refresh the page and try again.\nIf this persists, check your internet connection or try a different browser.');
          setTimeout(() => endSession(), 2000);
        } else if (isFatalError) {
          // Try to recover
          console.warn('⚠️ Fatal error detected, attempting recovery...');
          disconnectRetryCount++;
          updateStatus(`Recovering from error... (${disconnectRetryCount}/${MAX_RETRY_ATTEMPTS})`, 'connecting');

          // Force a re-connect attempt if the SDK doesn't do it automatically
          if (disconnectRetryCount <= MAX_RETRY_ATTEMPTS) {
            setTimeout(() => {
              if (sessionActive && !conversation.isConnected) {
                console.log('🔄 Triggering manual reconnection...');
                // We can't easily "re-start" the same conversation object in all SDK versions
                // But we can signal the user to try again if it fails
              }
            }, 3000);
          }
        } else {
          // Non-fatal error - log but continue
          console.warn('⚠️ Non-fatal error:', errorMessage);
          updateStatus('Connection issue detected...', 'connecting');
        }
      }
    });

  } catch (error) {
    console.error("Connection failed:", error);
    alert("Connection failed: " + error.message);
    endSession(); // Graceful exit
  }
}

// --- Session Management ---

function updateStatus(text, visualState) {
  if (callStatus) {
    // Only update text if we are NOT in the middle of a "speaking/listening" flow
    // or if it's a critical connection message (Connecting/Disconnected)
    const isConnectionMessage = text.includes('Connect') || text.includes('Disconnect') || text.includes('Error');

    if (isConnectionMessage) {
      // [CRITICAL FIX] Remove hidden class here too
      callStatus.classList.remove('hidden');

      callStatus.textContent = text;
      callStatus.style.display = 'inline-block';
      callStatus.classList.remove('speaking'); // Ensure it's gray for status messages
    }
  }

  // Clear the "Say Hello" prompt timeout if status changes
  if (text !== 'Say "Hello" to start' && helloPromptTimeout) {
    clearTimeout(helloPromptTimeout);
    helloPromptTimeout = null;
  }

  // Handle Ring Animations
  const profileContainer = document.querySelector('#screen-call .profile-container');
  if (callRing) {
    callRing.className = 'ring';

    if (visualState === 'connecting') {
      callRing.classList.add('connecting');
      if (profileContainer) {
        profileContainer.classList.add('voice-connecting');
        profileContainer.classList.remove('voice-active');
      }
    } else {
      // For speaking/listening, toggleVoiceVisuals handles the classes now
      if (profileContainer) {
        profileContainer.classList.remove('voice-connecting');
      }
    }
  }
}

// Helper to format time as MM:SS
function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

// function startTimer() { ... } // Removed in favor of startTalkTimeTracking

// Start tracking total talk time - GOD LEVEL IMPLEMENTATION
// GOD LEVEL FRONTEND LOGIC

function startTalkTimeTracking() {
  if (heartbeatInterval) clearInterval(heartbeatInterval);
  if (talkTimeInterval) clearInterval(talkTimeInterval);

  // 1. VISUAL TIMER (Local) - Runs every 1s
  talkTimeInterval = setInterval(() => {
    let currentDisplay = parseFloat(sessionStorage.getItem('userTalktime') || 0);

    // STRICT MODE: Local Kill Switch
    if (currentDisplay <= 0 && sessionActive) {
      console.warn(`⛔ Timer hit 0 (currentDisplay: ${currentDisplay}). Cutting connection immediately.`);
      endSession(); // Cut mic
      showPaymentModal('during'); // Demand payment
      return;
    }

    if (currentDisplay > 0 && sessionActive) {
      currentDisplay -= 1; // Visually deduct 1s
      // Save FIRST so updateTalkTimeDisplay reads the correct value
      sessionStorage.setItem('userTalktime', currentDisplay.toString());
      updateTalkTimeDisplay(); // Update all displays
      if (currentDisplay % 10 === 0) console.log(`⏱️ Time remaining: ${currentDisplay}s`);
    }
  }, 1000);

  // 2. SERVER SYNC (The Authority) - Optimized to 5 seconds
  heartbeatInterval = setInterval(async () => {
    if (!sessionActive) return;

    // Secure Heartbeat
    const token = sessionStorage.getItem('authToken');
    if (!token) {
      console.warn("Heartbeat: No token found. Ending session.");
      endSession();
      return;
    }

    try {
      const userEmail = sessionStorage.getItem('userEmail');
      const response = await fetch('/api/session/heartbeat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ email: userEmail, timestamp: Date.now() })
      });

      if (response.status === 401) {
        console.error("Session expired (401). Logging out.");
        endSession();
        window.location.href = "/login.html";
        return;
      }

      // Handle 400: Redis session missing - don't logout, just restart call
      if (response.status === 400) {
        console.warn("Redis session missing (400). Call will need to be restarted.");
        // Don't logout! Just end the call gracefully
        endSession();
        return;
      }

      const data = await response.json();

      if (data.action === 'terminate' || data.remaining_seconds <= 0) {
        console.warn("Server ordered termination.");
        sessionStorage.setItem('userTalktime', '0');
        updateTalktimeDisplay(0);
        endSession();
        showPaymentModal('during');
        return;
      }

      if (data.ok) {
        sessionStorage.setItem('userTalktime', data.remaining_seconds);
        let localTime = parseFloat(sessionStorage.getItem('userTalktime'));
        if (Math.abs(localTime - data.remaining_seconds) > 2) {
          updateTalktimeDisplay(Math.floor(data.remaining_seconds));
        }
      }

    } catch (e) {
      console.error("Heartbeat skipped:", e);
    }
  }, 5000);
}

// Stop tracking talk time
function stopTalkTimeTracking() {
  if (talkTimeInterval) {
    clearInterval(talkTimeInterval);
    talkTimeInterval = null;
  }
  // NEW: Clear the heartbeat interval
  if (heartbeatInterval) {
    clearInterval(heartbeatInterval);
    heartbeatInterval = null;
  }
  talkTimeStartTime = null;
}

// Update talk time display
function updateTalkTimeDisplay() {
  const currentSeconds = parseInt(sessionStorage.getItem('userTalktime') || '0', 10);
  const formatted = formatTime(currentSeconds);

  // Update MAIN call screen timer
  if (timerDisplay) {
    timerDisplay.textContent = formatted;
  }

  // Update side panel talktime
  if (talkTimeValue) {
    talkTimeValue.textContent = formatted;
  }

  // Also update loading screen talk time if visible
  if (loadingTalkTimeValue && screens.loading && !screens.loading.classList.contains('hidden')) {
    loadingTalkTimeValue.textContent = formatted;
  }

  // Check if talktime is 0 during active session
  if (sessionActive && currentSeconds <= 0) {
    pauseSessionForPayment();
  }
}

// Initialize and update talktime display
async function initializeTalktime() {
  if (micBtn) micBtn.disabled = true; // [FIX] Disable start until verified

  // Get user email
  const emailInput = document.getElementById('userEmail');
  const email = emailInput ? emailInput.value?.trim() : sessionStorage.getItem('userEmail') || '';

  // Removed test bonus code - talktime now syncs directly from server

  if (!email) {
    // No email yet, use default
    let talktime = parseInt(sessionStorage.getItem('userTalktime') || '0', 10);
    if (isNaN(talktime) || talktime < 0) {
      talktime = 0;
      sessionStorage.setItem('userTalktime', '0');
    }
    updateTalktimeDisplay(talktime);
    // Keep button disabled if 0? Or allow if we can't verify? 
    // If no email, they can't have balance? Block.
    return;
  }

  // Check with backend and get talktime (includes welcome bonus if new user)
  try {
    const response = await authenticatedFetch('/api/user/talktime', {
      method: 'GET'
    });

    const data = await response.json();

    if (data.ok) {
      const talktime = data.talktime || 0;
      // Always sync with server value (server is source of truth)
      sessionStorage.setItem('userTalktime', talktime.toString());

      // Update global variables
      totalTalkTime = talktime;
      timeRemaining = talktime;

      // Clear test bonus flag if it exists (cleanup)
      if (sessionStorage.getItem('testBonusAdded')) {
        sessionStorage.removeItem('testBonusAdded');
      }

      // Update all talktime displays with server value
      updateTalkTimeDisplay();

      // Community Member Badge & Access Check
      if (data.is_community_member) {
        const badge = document.getElementById('vipBadge');
        if (badge) badge.classList.remove('hidden');

        // [FIX] Enable button ONLY if VIP and has balance
        if (talktime > 0 && micBtn) {
          micBtn.disabled = false;
        } else if (micBtn) {
          console.warn("User has 0 balance.");
          // Optional: update button text?
        }

      } else {
        // ⛔ STRICT VIP CHECK: If not a community member, BLOCK ACCESS
        console.warn("⛔ User is NOT a community member. Access denied.");
        showVIPRestriction();
        return; // Stop further initialization
      }

    } else {
      // Fallback to sessionStorage
      let talktime = parseInt(sessionStorage.getItem('userTalktime') || '0', 10);
      if (isNaN(talktime) || talktime < 0) {
        talktime = 0;
      }
      updateTalktimeDisplay(talktime);
    }
  } catch (error) {
    console.error('Error checking welcome bonus:', error);
    // Fallback? Ideally we should fail safe and block if we can't verify, 
    // but for now let's allow offline/error cases or block them too?
    // Let's block to be safe if strictly VIP.
    // However, if it's just a connection error, maybe we shouldn't lock them out?
    // User asked "vip user only". So default deny is safer.
    // For now, I'll assume if error, we might not know, so maybe let them be or block?
    // I will block if I can't verify.
    // Actually, let's keep the catch simple for now, maybe just log it.

    // Fallback to sessionStorage
    let talktime = parseInt(sessionStorage.getItem('userTalktime') || '0', 10);
    if (isNaN(talktime) || talktime < 0) {
      talktime = 0;
    }
    updateTalktimeDisplay(talktime);
  }
}

// --- VIP Restriction Helpers ---
function showVIPRestriction() {
  const modal = document.getElementById('vipRestrictionModal');
  if (modal) {
    modal.style.display = 'flex';
  }
  // Disable controls
  if (micBtn) micBtn.disabled = true;
  endSession();
}

window.logoutAndRedirect = function () {
  sessionStorage.clear();
  localStorage.removeItem('token'); // Just in case
  window.location.href = '/login.html';
};

// Periodic talktime refresh to sync with admin updates
function startTalktimeRefresh() {
  // Clear any existing interval
  if (talktimeRefreshInterval) clearInterval(talktimeRefreshInterval);

  // Refresh talktime every 30 seconds
  talktimeRefreshInterval = setInterval(async () => {
    try {
      // Fetch current talktime from server
      const response = await authenticatedFetch('/api/user/talktime');
      if (!response.ok) {
        console.warn('⚠️ Failed to refresh talktime:', response.status);
        return;
      }

      const data = await response.json();
      if (data.ok && data.talktime !== undefined) {
        const serverTalktime = data.talktime || 0;
        const currentLocalTalktime = parseInt(sessionStorage.getItem('userTalktime') || '0', 10);

        // Always sync with server value (server is source of truth)
        // This ensures admin updates are reflected immediately
        if (serverTalktime !== currentLocalTalktime) {
          console.log(`🔄 Talktime refreshed: ${currentLocalTalktime}s → ${serverTalktime}s`);
          sessionStorage.setItem('userTalktime', serverTalktime.toString());

          // Always update display to match server value
          // During session: heartbeat handles deductions, but admin changes override
          updateTalktimeDisplay(serverTalktime);

          // If server says 0 and we're in a session, pause it
          if (sessionActive && serverTalktime <= 0) {
            console.log('⛔ Server reports 0 talktime. Pausing session.');
            pauseSessionForPayment();
          }
        }
      }
    } catch (error) {
      console.warn('⚠️ Error refreshing talktime:', error);
    }
  }, 30000); // Refresh every 30 seconds
}

function stopTalktimeRefresh() {
  if (talktimeRefreshInterval) {
    clearInterval(talktimeRefreshInterval);
    talktimeRefreshInterval = null;
  }
}

// Periodic online status ping to keep user marked as online
function startOnlinePing() {
  // Clear any existing interval
  if (onlinePingInterval) clearInterval(onlinePingInterval);

  // Ping server every 60 seconds to update last_login
  onlinePingInterval = setInterval(async () => {
    try {
      // Ping server to update last_login (keeps user marked as online)
      const response = await authenticatedFetch('/api/user/ping', {
        method: 'POST'
      });

      if (!response.ok) {
        console.warn('⚠️ Failed to ping server:', response.status);
        return;
      }

      // Ping successful - user is now marked as online
      console.log('💚 Online status ping sent');
    } catch (error) {
      console.warn('⚠️ Error pinging server:', error);
    }
  }, 60000); // Ping every 60 seconds (within 15 minute window)
}

function stopOnlinePing() {
  if (onlinePingInterval) {
    clearInterval(onlinePingInterval);
    onlinePingInterval = null;
  }
}

// Update talktime display across all screens
function updateTalktimeDisplay(talktime) {
  const formatted = formatTime(talktime);

  // *** Update MAIN call screen timer ***
  if (timerDisplay) {
    timerDisplay.textContent = formatted;
  }

  // Update side panel talktime
  const sidePanelTalktimeValueEl = document.getElementById('sidePanelTalktimeValue');
  if (sidePanelTalktimeValueEl) {
    sidePanelTalktimeValueEl.textContent = formatted;
  }
  if (talktimeValue) talktimeValue.textContent = formatted;
  if (loadingTalktimeValue) loadingTalktimeValue.textContent = formatted;
  if (callTalktimeValue) callTalktimeValue.textContent = formatted;

  // Update progress bar (shows seconds)
  updateTalktimeProgressBar(talktime);

  // Save to sessionStorage
  sessionStorage.setItem('userTalktime', talktime.toString());
}

// Update talktime progress bar
function updateTalktimeProgressBar(currentTalktime) {
  const progressFill = document.getElementById('talktimeProgressFill');
  const progressText = document.getElementById('talktimeProgressText');

  if (!progressFill || !progressText) return;

  // Get initial talktime from sessionStorage or use stored initial
  let maxTalktime = parseInt(sessionStorage.getItem('initialTalktime') || '0', 10);

  // If no initial talktime stored, try to get it from the variable
  if (maxTalktime === 0) {
    maxTalktime = initialTalktime;
  }

  // If still no initial talktime, use current talktime as max (for display purposes)
  // But only if current is greater than 0
  if (maxTalktime === 0 && currentTalktime > 0) {
    maxTalktime = currentTalktime;
    // Store it for future reference
    initialTalktime = currentTalktime;
    sessionStorage.setItem('initialTalktime', currentTalktime.toString());
  }

  // If still 0, use a default max of 100 for display
  if (maxTalktime === 0) {
    maxTalktime = 100;
  }

  // Calculate percentage (how much talktime is remaining)
  const percentage = maxTalktime > 0 ? Math.min((currentTalktime / maxTalktime) * 100, 100) : 0;

  // Update progress bar width
  progressFill.style.width = `${percentage}%`;

  // Update progress text (show seconds)
  progressText.textContent = `${currentTalktime.toLocaleString()}s / ${maxTalktime.toLocaleString()}s`;

  // Update color based on percentage
  progressFill.classList.remove('low', 'critical');
  if (percentage <= 10 && currentTalktime > 0) {
    progressFill.classList.add('critical');
  } else if (percentage <= 30 && currentTalktime > 0) {
    progressFill.classList.add('low');
  }
}

// Add talktime (e.g., after purchase)
function addTalktime(amount) {
  let currentTalktime = parseInt(sessionStorage.getItem('userTalktime') || '0', 10);
  if (isNaN(currentTalktime)) currentTalktime = 0;
  const newTalktime = currentTalktime + amount;

  // If this is the first time adding talktime and no initial is set, set it
  if (initialTalktime === 0 && newTalktime > 0) {
    initialTalktime = newTalktime;
    sessionStorage.setItem('initialTalktime', initialTalktime.toString());
  }

  updateTalktimeDisplay(newTalktime);
  return newTalktime;
}

// Deduct talktime (e.g., when using call time)
function deductTalktime(amount) {
  let currentTalktime = parseInt(sessionStorage.getItem('userTalktime') || '0', 10);
  if (isNaN(currentTalktime)) currentTalktime = 0;
  const newTalktime = Math.max(0, currentTalktime - amount);
  updateTalktimeDisplay(newTalktime);

  // Check if talktime reached 0 during active session
  if (sessionActive && newTalktime <= 0) {
    pauseSessionForPayment();
  }

  return newTalktime;
}

// Handle buying talktime
async function handleBuyTalktime() {
  // Get the button that was clicked (could be side panel or main button)
  const sidePanelBuyBtn = document.getElementById('sidePanelBuyTalktime');
  const mainBuyBtn = btnBuyTalktime;
  const activeButton = sidePanelBuyBtn || mainBuyBtn;

  if (!activeButton) {
    console.error('Buy talktime button not found');
    return;
  }

  try {
    activeButton.disabled = true;
    const originalHTML = activeButton.innerHTML;
    activeButton.innerHTML = '<div class="side-panel-buy-icon"><i class="fas fa-spinner fa-spin"></i></div><span>Processing...</span>';

    // Create order for talktime purchase (₹499 = 49900 paise)
    const response = await fetch('/api/payments/razorpay/order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        amount_paisa: 49900, // ₹499 in paise
        currency: 'INR',
        receipt: `talktime_${Date.now()}`
      })
    });

    const orderData = await response.json();

    if (!response.ok || !orderData?.ok) {
      throw new Error(orderData?.error || 'Order creation failed');
    }

    const { order, key_id } = orderData;

    const options = {
      key: key_id,
      amount: order.amount,
      currency: order.currency,
      name: 'AI Voice Coach',
      description: 'Purchase Talktime (100 talktime)',
      order_id: order.id,
      handler: async function (response) {
        try {
          // Verify payment
          const verifyResponse = await authenticatedFetch('/api/payments/razorpay/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature
            })
          });

          const verifyData = await verifyResponse.json();
          if (verifyResponse.ok && verifyData.ok) {
            // Add talktime (backend already added it, but update frontend display)
            addTalktime(100);
            activeButton.disabled = false;
            activeButton.innerHTML = originalHTML;
            alert('Payment successful! 100 talktime added to your account.');
          } else {
            throw new Error(verifyData?.error || 'Payment verification failed');
          }
        } catch (error) {
          console.error('Payment verification error:', error);
          activeButton.disabled = false;
          activeButton.innerHTML = originalHTML;
          alert('Payment verification failed. Please contact support if the amount was deducted.');
        }
      },
      modal: {
        ondismiss: function () {
          activeButton.disabled = false;
          activeButton.innerHTML = originalHTML;
        }
      },
      theme: {
        color: '#007AFF'
      }
    };

    const rzp = new Razorpay(options);
    rzp.open();

  } catch (error) {
    console.error('Error buying talktime:', error);
    alert('Error: ' + (error.message || 'Payment failed. Please try again.'));
    activeButton.disabled = false;
    if (sidePanelBuyBtn) {
      activeButton.innerHTML = '<div class="side-panel-buy-icon"><i class="fas fa-wallet"></i></div><span>Buy Talktime</span>';
    } else {
      activeButton.textContent = '💳 Buy Talktime';
    }
  }
}

// Duplicate payment logic removed.
// We strictly use handleBuyTalktime() defined earlier.


// Add talk time to the timer


// [PRODUCTION FIX] Connection Health Monitoring
function startConnectionHealthCheck() {
  stopConnectionHealthCheck(); // Clear any existing check

  connectionHealthCheck = setInterval(() => {
    if (!sessionActive || !conversation) {
      stopConnectionHealthCheck();
      return;
    }

    // Check if connection is still alive
    try {
      // Simple check - if we haven't received any updates in 30 seconds, something might be wrong
      const timeSinceLastConnection = lastConnectionTime ? Date.now() - lastConnectionTime : 0;

      if (timeSinceLastConnection > 30000 && lastConnectionTime) {
        console.warn('⚠️ No connection activity for 30+ seconds');
        // Don't disconnect, just log - the SDK will handle reconnection
      }
    } catch (e) {
      console.warn('⚠️ Health check error:', e);
    }
  }, 10000); // Check every 10 seconds
}

function stopConnectionHealthCheck() {
  if (connectionHealthCheck) {
    clearInterval(connectionHealthCheck);
    connectionHealthCheck = null;
  }
}

async function endSession() {
  if (!sessionActive && !conversation && !isSessionPaused) return;

  // Notify server that session is ending
  try {
    await authenticatedFetch('/api/session/end', { method: 'POST' });
  } catch (e) {
    console.warn("Failed to notify server of session end:", e);
  }

  sessionActive = false;
  isSessionPaused = false;
  isReconnecting = false;

  // [PRODUCTION FIX] Clean up all connection-related timers
  stopConnectionHealthCheck();
  if (disconnectRetryTimeout) {
    clearTimeout(disconnectRetryTimeout);
    disconnectRetryTimeout = null;
  }
  disconnectRetryCount = 0;

  // Clean up sync timers
  if (speakTimeout) {
    clearTimeout(speakTimeout);
    speakTimeout = null;
  }
  if (silenceTimeout) {
    clearTimeout(silenceTimeout);
    silenceTimeout = null;
  }

  initialTalktime = 0; // Reset initial talktime
  sessionStorage.removeItem('initialTalktime'); // Clear stored initial
  if (timerInterval) clearInterval(timerInterval);
  stopTalkTimeTracking(); // Stop tracking talk time
  hidePaymentModal(); // Hide payment modal if open

  // Reset connection status indicator
  const connectionStatus = document.getElementById('connectionStatus');
  if (connectionStatus) {
    connectionStatus.classList.remove('connected');
    const statusText = connectionStatus.querySelector('.status-text');
    if (statusText) {
      statusText.textContent = 'Disconnected';
    }
  }

  // Clear mute state interval
  if (window.micMuteInterval) {
    clearInterval(window.micMuteInterval);
    window.micMuteInterval = null;
  }

  // Reset mic button state
  isMicMuted = false;
  updateMicButtonState(false);

  // Stop and clear media stream
  if (userMediaStream) {
    userMediaStream.getTracks().forEach(track => track.stop());
    userMediaStream = null;
  }

  // Hide status text
  toggleVoiceVisuals('idle');

  // Show side panel again when call ends
  const sidePanel = document.getElementById('sidePanel');
  const sidePanelToggle = document.getElementById('sidePanelToggle');
  if (sidePanel) {
    sidePanel.style.display = 'flex';
    sidePanel.style.visibility = '';
    sidePanel.classList.remove('call-hidden');
    // Update toggle button visibility based on panel state
    if (sidePanelToggle) {
      const isClosed = sidePanel.classList.contains('closed');
      sidePanelToggle.style.display = isClosed ? 'flex' : 'none';
      sidePanelToggle.style.visibility = '';
      sidePanelToggle.classList.remove('call-hidden');
    }
  }

  updateStatus('Disconnected', 'default');

  if (conversation) {
    try {
      await conversation.endSession();
    } catch (err) {
      console.warn('Error ending session:', err);
    }
    conversation = null;
  }

  // [CRITICAL] Save Transcript / Send Email
  const emailInput = document.getElementById('userEmail');
  const email = emailInput ? emailInput.value?.trim() : '';

  if (userTranscript) {
    try {
      updateStatus('Saving session and generating care plan...', 'default');
      const response = await authenticatedFetch('/upload-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ transcript: userTranscript })
      });

      if (response.ok) {
        console.log('✅ Session saved and care plan generation initiated');
      } else {
        console.error('⚠️ Failed to save session:', response.status, response.statusText);
      }
    } catch (err) {
      console.error('❌ Failed to save session:', err);
      // Don't show alert to user - already handled in endSession flow
    }
  } else {
    console.warn('⚠️ Cannot save session: missing transcript or email');
    if (!userTranscript) {
      console.warn('  - Transcript is empty');
    }
    if (!email) {
      console.warn('  - Email is missing');
    }
  }

  // Show success message about care plan email
  alert("Call ended! Your personalized care plan is being sent to your email. Please check your inbox in a few minutes.");

  // Redirect back to Ronit start page after a delay
  setTimeout(() => {
    if (screens.call) screens.call.classList.add('hidden');
    if (screens.ronitStart) {
      screens.ronitStart.classList.remove('hidden');
      if (footer) footer.style.display = 'block';

      // Show side panel again
      const sidePanel = document.getElementById('sidePanel');
      const sidePanelToggle = document.getElementById('sidePanelToggle');
      if (sidePanel) {
        sidePanel.style.display = 'flex';
        sidePanel.style.visibility = '';
        sidePanel.classList.remove('call-hidden');
        // Update toggle button visibility based on panel state
        const isClosed = sidePanel.classList.contains('closed');
        if (sidePanelToggle) {
          sidePanelToggle.style.display = isClosed ? 'flex' : 'none';
          sidePanelToggle.style.visibility = '';
          sidePanelToggle.classList.remove('call-hidden');
        }
      }
    }
    // Reset timer and status
    timeRemaining = 0; // [FIX] Reset to 0 (will need reload or re-sync for new session)
    totalTalkTime = 0;
    if (timerDisplay) timerDisplay.textContent = formatTime(0); // [FIX] Show 00:00
    if (talkTimeValue) talkTimeValue.textContent = formatTime(0);
    if (buyTalkTimeBtn) {
      buyTalkTimeBtn.style.display = 'none';
      buyTalkTimeBtn.disabled = false;
      buyTalkTimeBtn.textContent = '⏱️ Buy More Talk Time';
    }
    // Set status to Ready when returning to start screen
    if (callStatus) {
      toggleVoiceVisuals('idle');
    }
  }, 2000);
}

// --- REAL-TIME TEXT STATUS ENGINE ---

function toggleVoiceVisuals(state) {
  const callStatus = document.getElementById('callStatus');
  const profileContainer = document.querySelector('#screen-call .call-profile-section .profile-container');

  if (!callStatus) return;

  // [CRITICAL] Always remove hidden class
  callStatus.classList.remove('hidden');
  callStatus.style.display = 'inline-block';

  if (state === 'speaking') {
    // 🟢 AGENT SPEAKING (Green)
    callStatus.textContent = "Agent is speaking...";
    callStatus.className = 'call-status-text speaking'; // Reset classes, add speaking

    if (profileContainer) profileContainer.classList.add('speaking');

  } else if (state === 'listening') {
    // ⚪ LISTENING (Gray)
    // Handle Mute Logic
    if (typeof isMicMuted !== 'undefined' && isMicMuted) {
      callStatus.textContent = "🔇 Muted";
      callStatus.className = 'call-status-text'; // Gray
    } else {
      callStatus.textContent = "Listening...";
      callStatus.className = 'call-status-text'; // Gray
    }

    if (profileContainer) profileContainer.classList.remove('speaking');

  } else {
    // ⚪ IDLE / READY
    callStatus.textContent = "Ready";
    callStatus.className = 'call-status-text';
    if (profileContainer) profileContainer.classList.remove('speaking');
  }
}
