import { useEffect, useState } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { loadSession } from "../api";

export default function RequireSession() {
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const expired = () => setStatus("signed-out");
    window.addEventListener("acc-session-expired", expired);
    setStatus("loading");
    loadSession().then(() => {
      if (!cancelled) setStatus("authenticated");
    }).catch((error) => {
      if (cancelled) return;
      if (error.status === 401) {
        localStorage.removeItem("accUser");
        setStatus("signed-out");
      } else {
        setError(error.message);
        setStatus("error");
      }
    });
    return () => {
      cancelled = true;
      window.removeEventListener("acc-session-expired", expired);
    };
  }, [attempt]);

  if (status === "signed-out") return <Navigate to="/login" replace state={{ sessionExpired: true }} />;
  if (status === "authenticated") return <Outlet />;
  return <div className="auth-page" role="status">
    <p>{status === "loading" ? "Checking your session..." : error}</p>
    {status === "error" && <button type="button" onClick={() => setAttempt(value => value + 1)}>Try again</button>}
  </div>;
}
