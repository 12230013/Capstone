import { useState } from "react";
import { Eye, EyeOff, ChevronDown } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

function Signup() {

  const navigate = useNavigate();

  const [showPassword, setShowPassword] = useState(false);

  const [formData, setFormData] = useState({
    name: "",
    employee_id: "",
    email: "",
    role: "",
    department: "",
    password: ""
  });

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);


  // Handle input changes
  const handleChange = (e) => {

    const { name, value } = e.target;

    setFormData({
      ...formData,
      [name]: value
    });

    // Clear previous messages when user starts typing
    setError("");
    setSuccess("");
  };


  // Handle signup
  const handleSubmit = async (e) => {

    e.preventDefault();

    setError("");
    setSuccess("");
    setLoading(true);

    try {

      const response = await fetch(
        "http://127.0.0.1:8000/api/auth/signup",
        {
          method: "POST",

          headers: {
            "Content-Type": "application/json"
          },

          body: JSON.stringify(formData)
        }
      );


      const data = await response.json();


      if (!response.ok) {

  console.log("Backend validation error:", data);

  if (Array.isArray(data.detail)) {

    const messages = data.detail.map(
      (error) => {
        console.log("Validation error:", error);

        return `${error.loc?.join(".")}: ${error.msg}`;
      }
    );

    setError(messages.join(" | "));

  } else {

    setError(
      data.detail || "Signup failed. Please try again."
    );

  }

  return;
}


      // Signup successful
      setSuccess(
        "Account created successfully! Redirecting to login..."
      );


      // Clear form
      setFormData({
        name: "",
        employee_id: "",
        email: "",
        role: "",
        department: "",
        password: ""
      });


      // Redirect to login
      setTimeout(() => {
        navigate("/login");
      }, 1500);


    } catch (error) {

      console.error("Signup error:", error);

      setError(
        "Unable to connect to the server. Please make sure the backend is running."
      );

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


      {/* Signup Card */}
      <div className="auth-card signup-card">

        <h2>Sign up to access the chatbot</h2>


        {/* Error Message */}
        {error && (
          <div className="error-message">
            {error}
          </div>
        )}


        {/* Success Message */}
        {success && (
          <div className="success-message">
            {success}
          </div>
        )}


        <form onSubmit={handleSubmit}>

          {/* Name */}
          <div className="form-group">

            <label htmlFor="name">
              NAME
            </label>

            <input
              type="text"
              id="name"
              name="name"
              placeholder="eg: Dorji Gyelshen"
              value={formData.name}
              onChange={handleChange}
              required
            />

          </div>


          {/* Employee ID */}
          <div className="form-group">

            <label htmlFor="employee_id">
              EMPLOYEE ID
            </label>

            <input
              type="text"
              id="employee_id"
              name="employee_id"
              placeholder="eg: ACC001"
              value={formData.employee_id}
              onChange={handleChange}
              required
            />

          </div>


          {/* Email */}
          <div className="form-group">

            <label htmlFor="email">
              EMAIL
            </label>

            <input
              type="email"
              id="email"
              name="email"
              placeholder="eg: acc.staff@acc.org.bt"
              value={formData.email}
              onChange={handleChange}
              required
            />

          </div>


          {/* Role */}
          <div className="form-group">

            <label htmlFor="role">
              ROLE
            </label>

            <div className="select-wrapper">

              <select
                id="role"
                name="role"
                value={formData.role}
                onChange={handleChange}
                required
              >

                <option value="" disabled>
                  Select your role
                </option>

                <option value="Admin">
                  Admin
                </option>

                <option value="Director">
                  Director
                </option>

                <option value="Investigator">
                  Investigator
                </option>

                <option value="Team Members">
                  Team Members
                </option>

              </select>

              <ChevronDown
                className="select-icon"
                size={18}
              />

            </div>

          </div>


          {/* Department */}
          <div className="form-group">

            <label htmlFor="department">
              DEPARTMENT
            </label>

            <input
              type="text"
              id="department"
              name="department"
              placeholder="eg: Investigation Department"
              value={formData.department}
              onChange={handleChange}
              required
            />

          </div>


          {/* Password */}
          <div className="form-group">

            <label htmlFor="password">
              PASSWORD
            </label>

            <div className="password-input">

              <input
                type={showPassword ? "text" : "password"}
                id="password"
                name="password"
                placeholder="Enter your password"
                value={formData.password}
                onChange={handleChange}
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
                  <Eye size={18} />
                ) : (
                  <EyeOff size={18} />
                )}

              </button>

            </div>

          </div>


          {/* Sign Up */}
          <button
            type="submit"
            className="auth-button"
            disabled={loading}
          >

            {loading ? "Creating Account..." : "Sign Up"}

          </button>

        </form>


        {/* OR */}
        <div className="or-section">

          <span></span>

          <p>OR</p>

          <span></span>

        </div>


        {/* Login Link */}
        <div className="switch-auth">

          <span>
            Already have an account?
          </span>

          <Link to="/login">
            Sign in
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

export default Signup;