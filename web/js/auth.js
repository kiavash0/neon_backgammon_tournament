import { api, setTokens, ApiError } from "./api.js";

export function initAuthScreen({ onLoggedIn }) {
  const tabs = document.querySelectorAll(".tab");
  const panels = document.querySelectorAll(".tab-panel");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      document.querySelector(`#form-${tab.dataset.tab}`).classList.add("active");
    });
  });

  const loginForm = document.getElementById("form-login");
  const loginError = document.getElementById("login-error");
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.textContent = "";
    const data = Object.fromEntries(new FormData(loginForm));
    try {
      const tokens = await api.login(data);
      setTokens(tokens);
      onLoggedIn();
    } catch (err) {
      loginError.textContent = describeError(err);
    }
  });

  const signupForm = document.getElementById("form-signup");
  const signupError = document.getElementById("signup-error");
  signupForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    signupError.textContent = "";
    const data = Object.fromEntries(new FormData(signupForm));
    try {
      await api.signup(data);
      const tokens = await api.login({ email: data.email, password: data.password });
      setTokens(tokens);
      onLoggedIn();
    } catch (err) {
      signupError.textContent = describeError(err);
    }
  });
}

function describeError(err) {
  if (err instanceof ApiError) {
    if (err.status === 423) return "Too many failed attempts — account temporarily locked.";
    return err.message || "Something went wrong.";
  }
  return "Network error — is the server running?";
}
