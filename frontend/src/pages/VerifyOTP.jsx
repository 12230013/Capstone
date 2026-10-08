import { useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

function VerifyOTP() {
  const [otp, setOtp] = useState(["", "", "", "", "", ""]);

  const inputRefs = useRef([]);

  const navigate = useNavigate();
  const location = useLocation();

  const email = location.state?.email || "";

  const handleChange = (value, index) => {
    // Only allow numbers
    if (!/^\d?$/.test(value)) {
      return;
    }

    const newOtp = [...otp];
    newOtp[index] = value;

    setOtp(newOtp);

    // Move to next box
    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (e, index) => {
    // Move to previous box when backspace is pressed
    if (
      e.key === "Backspace" &&
      !otp[index] &&
      index > 0
    ) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();

    const enteredOTP = otp.join("");

    if (enteredOTP.length !== 6) {
      alert("Please enter the complete OTP.");
      return;
    }

    // Backend/OTP verification will be connected later
    console.log("OTP:", enteredOTP);
    console.log("Email:", email);

    navigate("/reset-password", {
      state: { email },
    });
  };

  return (
    <div className="auth-page forgot-page">

      <div className="otp-card">

        <form onSubmit={handleSubmit}>

          <div className="otp-title">
            OTP
          </div>

          <div className="otp-container">

            {otp.map((digit, index) => (
              <input
                key={index}
                ref={(element) => {
                  inputRefs.current[index] = element;
                }}
                type="text"
                inputMode="numeric"
                maxLength="1"
                value={digit}
                onChange={(e) =>
                  handleChange(e.target.value, index)
                }
                onKeyDown={(e) =>
                  handleKeyDown(e, index)
                }
                className="otp-input"
              />
            ))}

          </div>

          <button type="submit" className="auth-button otp-button">
            Enter
          </button>

        </form>

      </div>

    </div>
  );
}

export default VerifyOTP;