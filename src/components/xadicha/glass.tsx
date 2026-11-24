"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { forwardRef, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/**
 * Liquid Glass primitivlari. Material (rang, xiralik, qirra, yorug'lik) globals.css'dagi `.glass*` sinflarida —
 * bu yerda faqat shakl va xatti-harakat. Ichma-ich shisha uchun `subtle` (qayta xiralashtirilmaydi).
 */
type Variant = "default" | "strong" | "subtle";
const VARIANT: Record<Variant, string> = { default: "glass", strong: "glass-strong", subtle: "glass-subtle" };

export function GlassPanel({ as: Tag = "section", variant = "default", className, children, ...rest }: {
  as?: "section" | "div" | "aside" | "header" | "nav" | "article";
  variant?: Variant;
  className?: string;
  children?: React.ReactNode;
} & Omit<React.HTMLAttributes<HTMLElement>, "className" | "children">) {
  return (
    <Tag {...rest} className={cn(VARIANT[variant], "rounded-[24px]", className)}>
      {children}
    </Tag>
  );
}

/** Panel sarlavhasi: kichik, tinch, chiziqsiz. */
export function PanelTitle({ children, hint, icon, className }: {
  children: React.ReactNode; hint?: React.ReactNode; icon?: React.ReactNode; className?: string;
}) {
  return (
    <div className={cn("mb-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-1", className)}>
      <h2 className="inline-flex items-center gap-2 text-[13px] font-medium tracking-wide text-muted-foreground">
        {icon}{children}
      </h2>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  );
}

export const GlassInput = forwardRef<HTMLInputElement, React.ComponentProps<"input">>(function GlassInput(
  { className, ...props }, ref,
) {
  return (
    <input
      ref={ref}
      {...props}
      className={cn(
        "h-11 min-w-0 rounded-2xl border border-white/10 bg-white/[0.04] px-4 text-[15px] text-foreground",
        "placeholder:text-faint transition-colors focus:border-primary/50 focus:bg-white/[0.06] focus-visible:outline-none",
        "focus-visible:ring-2 focus-visible:ring-primary/35 disabled:opacity-50",
        className,
      )}
    />
  );
});

/** Shisha modal: fon xiralashadi, fokus ichkarida qoladi, Esc — yopish (xavfsiz tanlov). */
export function GlassModal({ open, onClose, closeDisabled, labelledBy, describedBy, role = "dialog", busy, children, className }: {
  open: boolean;
  onClose: () => void;
  closeDisabled?: boolean;
  labelledBy: string;
  describedBy?: string;
  role?: "dialog" | "alertdialog";
  busy?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !closeDisabled) onClose();
      if (e.key === "Tab" && box.current) {
        const items = [...box.current.querySelectorAll<HTMLElement>("button:not([disabled]), a[href], input:not([disabled])")];
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        else if (!box.current.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, closeDisabled]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#05070d]/60 p-4 backdrop-blur-md"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
        >
          <motion.div
            ref={box} role={role} aria-modal="true" aria-labelledby={labelledBy} aria-describedby={describedBy} aria-busy={busy}
            className={cn("glass-strong w-full max-w-md rounded-[28px] p-6", className)}
            initial={reduce ? false : { y: 18, scale: 0.97, opacity: 0 }}
            animate={{ y: 0, scale: 1, opacity: 1 }}
            exit={reduce ? { opacity: 0 } : { y: 10, scale: 0.98, opacity: 0 }}
            transition={{ type: "spring", stiffness: 380, damping: 32 }}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Segmentli tanlov (til, rejim): faol element — shisha yoritish, siljiydi. */
export function Segmented<T extends string>({ value, options, onChange, label, layoutId, size = "sm" }: {
  value: T; options: { id: T; label: string; title?: string; lang?: string }[]; onChange: (v: T) => void;
  label: string; layoutId: string; size?: "sm" | "md";
}) {
  return (
    <div role="radiogroup" aria-label={label}
      className="relative flex w-fit max-w-full flex-wrap gap-0.5 rounded-full border border-white/[0.07] bg-white/[0.03] p-1">
      {options.map((o) => (
        <button key={o.id} type="button" role="radio" aria-checked={value === o.id} onClick={() => onChange(o.id)}
          title={o.title} lang={o.lang}
          className={cn("relative rounded-full font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring",
            size === "sm" ? "px-3 py-1 text-xs" : "px-4 py-1.5 text-sm",
            value === o.id ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
          {value === o.id && (
            <motion.span layoutId={layoutId} className="glass-active absolute inset-0 rounded-full"
              transition={{ type: "spring", stiffness: 420, damping: 36 }} />
          )}
          <span className="relative">{o.label}</span>
        </button>
      ))}
    </div>
  );
}
