import { useEffect, useRef } from "react";

export function formatAuthError(detail, fallback) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((issue) => {
      const field = issue.loc?.filter((part) => part !== "body").join(" ");
      return `${field ? `${field.replaceAll("_", " ")}: ` : ""}${issue.msg || fallback}`;
    }).join("\n");
  }
  return fallback;
}

export default function AuthError({ message }) {
  const alertRef = useRef(null);

  useEffect(() => {
    if (!message) return;
    alertRef.current?.focus({ preventScroll: true });
    alertRef.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [message]);

  if (!message) return null;

  return (
    <div className="auth-error" role="alert" tabIndex={-1} ref={alertRef}>
      {message}
    </div>
  );
}
