import type { ButtonHTMLAttributes } from "react";
import "./Button.css";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" };

/** A pill button; `type` defaults to "button" so that no button submits a form by accident. */
export function Button({ variant = "secondary", className = "", type = "button", ...rest }: Props) {
  return <button type={type} className={`pl-btn pl-btn-${variant} ${className}`.trim()} {...rest} />;
}
