#!/usr/bin/env python3
"""Simple GUI for generating product keys (owner only — do not distribute)."""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from make_key import KeyGenError, generate_product_key, init_keypair, private_key_exists  # noqa: E402


class KeyGenApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AcDec Product Key Generator")
        self.minsize(520, 420)
        self._build_ui()
        self._refresh_key_status()

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}

        header = ttk.Label(
            self,
            text="Generate machine-bound product keys",
            font=("Segoe UI", 12, "bold"),
        )
        header.pack(anchor="w", **pad)

        ttk.Label(
            self,
            text="Owner tool only. Never give this app or your private key to recipients.",
            wraplength=480,
        ).pack(anchor="w", padx=12)

        status_frame = ttk.LabelFrame(self, text="Signing key")
        status_frame.pack(fill="x", padx=12, pady=10)

        self.status_var = tk.StringVar()
        ttk.Label(status_frame, textvariable=self.status_var).pack(
            anchor="w", padx=10, pady=(8, 4)
        )

        btn_row = ttk.Frame(status_frame)
        btn_row.pack(anchor="w", padx=10, pady=(0, 8))
        self.init_btn = ttk.Button(btn_row, text="Initialize keypair", command=self._on_init)
        self.init_btn.pack(side="left")

        form = ttk.LabelFrame(self, text="New product key")
        form.pack(fill="x", padx=12, pady=4)

        ttk.Label(form, text="Recipient Machine ID").grid(row=0, column=0, sticky="w", padx=10, pady=6)
        self.machine_var = tk.StringVar()
        machine_entry = ttk.Entry(form, textvariable=self.machine_var, width=28, font=("Consolas", 10))
        machine_entry.grid(row=0, column=1, sticky="ew", padx=10, pady=6)
        ttk.Label(form, text="XXXX-XXXX-XXXX-XXXX", foreground="#666").grid(
            row=0, column=2, sticky="w", padx=4, pady=6
        )

        ttk.Label(form, text="Valid for (days)").grid(row=1, column=0, sticky="w", padx=10, pady=6)
        self.days_var = tk.StringVar(value="365")
        days_spin = ttk.Spinbox(form, from_=1, to=3650, textvariable=self.days_var, width=8)
        days_spin.grid(row=1, column=1, sticky="w", padx=10, pady=6)

        form.columnconfigure(1, weight=1)

        self.generate_btn = ttk.Button(form, text="Generate product key", command=self._on_generate)
        self.generate_btn.grid(row=2, column=0, columnspan=3, sticky="w", padx=10, pady=(4, 10))

        out_frame = ttk.LabelFrame(self, text="Result")
        out_frame.pack(fill="both", expand=True, padx=12, pady=10)

        self.output = tk.Text(out_frame, height=10, wrap="word", font=("Consolas", 10))
        self.output.pack(fill="both", expand=True, padx=10, pady=(8, 4))
        self.output.configure(state="disabled")

        copy_row = ttk.Frame(out_frame)
        copy_row.pack(anchor="e", padx=10, pady=(0, 8))
        ttk.Button(copy_row, text="Copy product key", command=self._on_copy).pack(side="right")

        self._product_key = ""

    def _refresh_key_status(self) -> None:
        ready = private_key_exists()
        if ready:
            self.status_var.set("Private key found. Ready to generate product keys.")
            self.init_btn.configure(state="disabled")
            self.generate_btn.configure(state="normal")
        else:
            self.status_var.set("No private key yet. Initialize once before generating keys.")
            self.init_btn.configure(state="normal")
            self.generate_btn.configure(state="disabled")

    def _set_output(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, text)
        self.output.configure(state="disabled")

    def _on_init(self) -> None:
        if not messagebox.askyesno(
            "Initialize keypair",
            "Create a new Ed25519 signing keypair?\n\n"
            "Only do this once. Keep the private key secret.\n"
            "You will need to paste the public key into backend/app/licensing.py "
            "before building the installer.",
        ):
            return
        try:
            public_b64 = init_keypair()
        except KeyGenError as exc:
            messagebox.showerror("Initialize failed", str(exc))
            return

        self._refresh_key_status()
        self._set_output(
            "Keypair created.\n\n"
            "Paste this into backend/app/licensing.py as PUBLIC_KEY_B64:\n\n"
            f"{public_b64}\n\n"
            "Rebuild the app/installer after updating licensing.py."
        )
        messagebox.showinfo("Keypair created", "Private key saved. See the Result box for the public key.")

    def _on_generate(self) -> None:
        machine_id = self.machine_var.get().strip()
        try:
            days = int(self.days_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid input", "Days must be a number.")
            return

        try:
            result = generate_product_key(machine_id, days)
        except KeyGenError as exc:
            messagebox.showerror("Generate failed", str(exc))
            return

        body = (
            f"Machine ID: {result.machine_id}\n"
            f"Expires:    {result.expires} (UTC)\n"
            f"Days:       {result.days}\n\n"
            f"Product key (send to recipient):\n\n"
            f"{result.key}"
        )
        self._set_output(body)
        self._product_key = result.key
        self.clipboard_clear()
        self.clipboard_append(result.key)

    def _on_copy(self) -> None:
        if not self._product_key:
            messagebox.showinfo("Copy", "Generate a product key first.")
            return
        self.clipboard_clear()
        self.clipboard_append(self._product_key)
        messagebox.showinfo("Copied", "Product key copied to clipboard.")


def main() -> None:
    app = KeyGenApp()
    app.mainloop()


if __name__ == "__main__":
    main()
