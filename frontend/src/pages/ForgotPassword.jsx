import { useState } from "react";
import { useNavigate } from "react-router-dom";

function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const response = await fetch(
        "http://127.0.0.1:8000/api/auth/forgot-password",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email.trim() }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to request OTP.");
      }

      navigate("/verify-otp", {
        state: { email: email.trim() },
      });
    } catch (err) {
      setError(err.message || "Unable to connect to the backend.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page forgot-page">
      <div className="forgot-card">
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="forgot-email">EMAIL</label>
            <input
              type="email"
              id="forgot-email"
              placeholder="eg:acc.staff@acc.org.bt"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          {error && <p style={{ color: "red" }}>{error}</p>}

          <button type="submit" className="auth-button" disabled={loading}>
            {loading ? "Sending..." : "Next"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default ForgotPassword;