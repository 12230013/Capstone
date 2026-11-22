export default function AuthPanel({ children }) {
  return (
    <div className="auth-page branded-auth-page">
      <div className="auth-card branded-auth-card">
        <div className="acc-header">
          <img
            src="/acc-logo.png"
            alt="Anti-Corruption Commission Logo"
            className="acc-logo"
          />
          <div className="auth-brand-text">
            <h1>Anti-Corruption Commission</h1>
            <p>KINGDOM OF BHUTAN</p>
          </div>
        </div>
        {children}
      </div>
      <footer>Copyright @2026 Anti Corruption Commission</footer>
    </div>
  );
}
