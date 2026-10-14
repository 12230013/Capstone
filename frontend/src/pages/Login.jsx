import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

function Login() {
  const [showPassword, setShowPassword] = useState(false);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();

    setError("");
    setLoading(true);

    try {
      const response = await fetch(
        "http://127.0.0.1:8000/api/auth/login",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            email: email,
            password: password,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Login failed");
      }

      console.log("Login successful:", data);

      // Save the logged-in user's details for the dashboard
      localStorage.setItem("accUser", JSON.stringify(data.user));

      // Go to dashboard after successful login
      navigate("/dashboard");

    } catch (error) {
      console.error("Login error:", error);
      setError(error.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">

      {/* ACC Header */}
      <div className="acc-header">

        <img
          src="/acc-logo.png"
          alt="Anti-Corruption Commission Logo"
          className="acc-logo"
        />

        <h1>Anti-Corruption Commission</h1>

        <p>KINGDOM OF BHUTAN</p>

        <div className="gold-line"></div>
      </div>


      {/* Login Card */}
      <div className="auth-card login-card">

        <h2>Sign in to access the chatbot</h2>

        <form onSubmit={handleSubmit}>

          {/* Email */}
          <div className="form-group">

            <label htmlFor="email">EMAIL</label>

            <input
              type="email"
              id="email"
              name="email"
              placeholder="eg:acc.staff@acc.org.bt"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />

          </div>


          {/* Password */}
          <div className="form-group password-group">

            <label htmlFor="password">PASSWORD</label>

            <div className="password-input">

              <input
                type={showPassword ? "text" : "password"}
                id="password"
                name="password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />

              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword(!showPassword)}
              >
                {showPassword ? (
                  <Eye size={21} />
                ) : (
                  <EyeOff size={21} />
                )}
              </button>

            </div>


            {/* Forgot Password */}
            <div className="forgot-password">

              <Link to="/forgot-password">
                Forgot Password?
              </Link>

            </div>

          </div>


          {/* Error Message */}
          {error && (
            <div className="login-error">
              {error}
            </div>
          )}


          {/* Sign In */}
          <button
            type="submit"
            className="auth-button"
            disabled={loading}
          >
            {loading ? "Signing In..." : "Sign In"}
          </button>

        </form>


        {/* OR */}
        <div className="or-section">

          <span></span>

          <p>OR</p>

          <span></span>

        </div>


        {/* Signup Link */}
        <div className="switch-auth">

          <span>Already have an account?</span>

          <Link to="/signup">
            Sign up
          </Link>

        </div>

      </div>


      {/* Footer */}
      <footer>
        Copyright @2026 Anti Corruption Commission
      </footer>

    </div>
  );
}

export default Login;