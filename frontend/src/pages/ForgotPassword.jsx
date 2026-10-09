import { useState } from "react";
import { useNavigate } from "react-router-dom";

function ForgotPassword() {
  const [email, setEmail] = useState("");
  const navigate = useNavigate();

  const handleSubmit = (e) => {
    e.preventDefault();

    // Backend/OTP API will be connected later
    console.log("OTP requested for:", email);

    navigate("/verify-otp", {
      state: { email },
    });
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

          <button type="submit" className="auth-button">
            Next
          </button>

        </form>

      </div>

    </div>
  );
}

export default ForgotPassword;