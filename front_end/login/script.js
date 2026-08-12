// ---------------------------------------------------------------
// Config — point this at your backend
// ---------------------------------------------------------------
const API_BASE_URL = "http://localhost:5000/api"; // change to your deployed URL
const LOGIN_ENDPOINT = `${API_BASE_URL}/auth/login`;
const GOOGLE_OAUTH_URL = `${API_BASE_URL}/auth/google`;   // your backend's Google OAuth redirect route
const FACEBOOK_OAUTH_URL = `${API_BASE_URL}/auth/facebook`; // your backend's Facebook OAuth redirect route

// ---------------------------------------------------------------
// Elements
// ---------------------------------------------------------------
const form = document.getElementById("login-form");
const statusEl = document.getElementById("status");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const rememberInput = document.getElementById("remember");
const submitBtn = document.getElementById("login-submit");
const googleBtn = document.getElementById("google-login");
const facebookBtn = document.getElementById("facebook-login");

// ---------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------
function setStatus(message, type = "error") {
  statusEl.textContent = message;
  statusEl.classList.toggle("is-success", type === "success");
}

function clearStatus() {
  statusEl.textContent = "";
  statusEl.classList.remove("is-success");
}

// ---------------------------------------------------------------
// Validation
// ---------------------------------------------------------------
function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function markInvalid(input, isInvalid) {
  input.classList.toggle("is-invalid", isInvalid);
}

document.querySelectorAll(".field input").forEach((input) => {
  input.addEventListener("input", () => markInvalid(input, false));
});

// ---------------------------------------------------------------
// Loading state
// ---------------------------------------------------------------
function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtn.classList.toggle("is-loading", isLoading);
}

// ---------------------------------------------------------------
// Session storage
// ---------------------------------------------------------------
function storeSession({ access_token, refresh_token } = {}, remember) {
  const store = remember ? localStorage : sessionStorage;
  if (access_token) store.setItem("access_token", access_token);
  if (refresh_token) store.setItem("refresh_token", refresh_token);
}

// ---------------------------------------------------------------
// Login submit
// ---------------------------------------------------------------
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearStatus();

  const email = emailInput.value.trim();
  const password = passwordInput.value;

  const emailValid = isValidEmail(email);
  const passwordValid = password.length >= 8;

  markInvalid(emailInput, !emailValid);
  markInvalid(passwordInput, !passwordValid);

  if (!emailValid || !passwordValid) {
    setStatus("Enter a valid email and a password of at least 8 characters.");
    return;
  }

  setLoading(true);

  try {
    const response = await fetch(LOGIN_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    let data = {};
    try {
      data = await response.json();
    } catch {
      // no JSON body
    }

    if (!response.ok) {
      const message = data.error || data.message || `Login failed (${response.status}).`;
      throw new Error(message);
    }

    storeSession(data, rememberInput.checked);
    setStatus("Logged in. Redirecting…", "success");

    setTimeout(() => {
      window.location.href = "/dashboard";
    }, 500);
  } catch (err) {
    setStatus(err.message || "Could not reach the server. Try again.");
  } finally {
    setLoading(false);
  }
});

// ---------------------------------------------------------------
// OAuth buttons — redirect to your backend's OAuth flow
// ---------------------------------------------------------------
googleBtn.addEventListener("click", () => {
  window.location.href = GOOGLE_OAUTH_URL;
});

facebookBtn.addEventListener("click", () => {
  window.location.href = FACEBOOK_OAUTH_URL;
});