import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

function ResetPassword() {
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] =
    useState(false);

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const navigate = useNavigate();
  const location = useLocation();

  const email = location.state?.email || "";

  const handleSubmit = (e) => {
    e.preventDefault();

    if (password !== confirmPassword) {
      alert("Passwords do not match.");
      return;
    }

    // Backend/password reset API will be connected later
    console.log("Password reset for:", email);

    alert("Password reset successfully.");

    navigate("/login");
  };

  return (
    <div className="auth-page forgot-page">

      <div className="reset-card">

        <form onSubmit={handleSubmit}>

          {/* New Password */}
          <div className="form-group password-group">

            <label htmlFor="new-password">
              New Password
            </label>

            <div className="password-input">

              <input
                type={
                  showPassword
                    ? "text"
                    : "password"
                }
                id="new-password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) =>
                  setPassword(e.target.value)
                }
                required
              />

              <button
                type="button"
                className="password-toggle"
                onClick={() =>
                  setShowPassword(!showPassword)
                }
              >
                {showPassword ? (
                  <Eye size={21} />
                ) : (
                  <EyeOff size={21} />
                )}
              </button>

            </div>

          </div>


          {/* Confirm Password */}
          <div className="form-group password-group">

            <label htmlFor="confirm-password">
              Confirm Password
            </label>

            <div className="password-input">

              <input
                type={
                  showConfirmPassword
                    ? "text"
                    : "password"
                }
                id="confirm-password"
                placeholder="Enter your password"
                value={confirmPassword}
                onChange={(e) =>
                  setConfirmPassword(e.target.value)
                }
                required
              />

              <button
                type="button"
                className="password-toggle"
                onClick={() =>
                  setShowConfirmPassword(
                    !showConfirmPassword
                  )
                }
              >
                {showConfirmPassword ? (
                  <Eye size={21} />
                ) : (
                  <EyeOff size={21} />
                )}
              </button>

            </div>

          </div>


          <button
            type="submit"
            className="auth-button reset-button"
          >
            Confirm
          </button>

        </form>

      </div>

    </div>
  );
}

export default ResetPassword;