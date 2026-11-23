"use server";

import { signIn, signOut } from "@/auth";

export async function signInWithGoogle() {
  await signIn("google", { redirectTo: "/" });
}

export async function signInAsDemo(formData: FormData) {
  const user = String(formData.get("user") ?? "");
  await signIn("demo", { user, redirectTo: "/" });
}

export async function signOutAction() {
  await signOut({ redirectTo: "/" });
}
