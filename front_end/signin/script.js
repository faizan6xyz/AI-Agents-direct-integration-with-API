const API_BASE_URL = "http://localhost:5000/api"; // change to your deployed URL
const SIGNUP_ENDPOINT = `${API_BASE_URL}/auth/signup`;
const GOOGLE_OAUTH_URL = `${API_BASE_URL}/auth/google`;   // your backend's Google OAuth redirect route
const FACEBOOK_OAUTH_URL = `${API_BASE_URL}/auth/facebook`; // your backend's Facebook OAuth redirect route
const form = document.getElementById("signup-form");
const statusEl = document.getElementById("status");
const fullNameInput = document.getElementById("full-name");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const confirmPasswordInput = document.getElementById("confirm-password");
const agreeTermsInput = document.getElementById("agree-terms");
const submitBtn = document.getElementById("signup-submit");
const googleBtn = document.getElementById("google-login");
const facebookBtn = document.getElementById("facebook-login");
function setStatus(message, type = "error") {
  statusEl.textContent = message;
  statusEl.classList.toggle("is-success", type === "success");
}
function clearStatus() {
  statusEl.textContent = "";
  statusEl.classList.remove("is-success");
}
function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}
function markInvalid(input, isInvalid) {
  input.classList.toggle("is-invalid", isInvalid);
}
document.querySelectorAll(".field input").forEach((input) => {
  input.addEventListener("input", () => markInvalid(input, false));
});
function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtn.classList.toggle("is-loading", isLoading);
}
function storeSession({ access_token, refresh_token } = {}) {
  if (access_token) localStorage.setItem("access_token", access_token);
  if (refresh_token) localStorage.setItem("refresh_token", refresh_token);
}
form.addEventListener("submit", async (event) => {  // runs after the forms submit button is pressed because it saya forms.addeventlistener
  event.preventDefault();  // (stops page reload)
  clearStatus(); // (wipes any old error message)
  const fullName = fullNameInput.value.trim();
  const email = emailInput.value.trim();
  const password = passwordInput.value;
  const confirmPassword = confirmPasswordInput.value;
  const nameValid = fullName.length >= 2;
  const emailValid = isValidEmail(email);
  const passwordValid = password.length >= 8;
  const confirmValid = confirmPassword.length >= 8 && confirmPassword === password;
  markInvalid(fullNameInput, !nameValid);
  markInvalid(emailInput, !emailValid);
  markInvalid(passwordInput, !passwordValid);
  markInvalid(confirmPasswordInput, !confirmValid);
  if (!nameValid) {
    setStatus("Enter your full name.");
    return;
  }
  if (!emailValid || !passwordValid) {
    setStatus("Enter a valid email and a password of at least 8 characters.");
    return;
  }
  if (password !== confirmPassword) {
    setStatus("Passwords do not match.");
    return;
  }
  if (!agreeTermsInput.checked) {
    setStatus("Please agree to the Terms & Conditions to continue.");
    return;
  }
  setLoading(true);
  try {
    const response = await fetch(SIGNUP_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name: fullName, email, password }),
    });

    let data = {};
    try {
      data = await response.json();
    } catch {
      // no JSON body
    }
    if (!response.ok) {
      const message = data.error || data.message || `Sign up failed (${response.status}).`;
      throw new Error(message);
    }
    storeSession(data);
    setStatus("Account created. Redirecting…", "success");
    setTimeout(() => {
    window.location.href = "https://www.mysite.com/dashboard";    }, 500);
  } catch (err) {
    setStatus(err.message || "Could not reach the server. Try again.");
  } finally {
    setLoading(false);
  }
});
googleBtn.addEventListener("click", () => {
  window.location.href = GOOGLE_OAUTH_URL;
});

facebookBtn.addEventListener("click", () => {
  window.location.href = FACEBOOK_OAUTH_URL;
});