import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";

/** Demo sign-in for the two synthetic users, so reviewers can try the personal tools
 *  without a Google account. Off unless ELKOLLEN_DEMO_LOGIN=true. Only invented data. */
const DEMO_USERS: Record<string, string> = { "demo-anna": "Anna (demo)", "demo-erik": "Erik (demo)" };
export const demoLoginEnabled = process.env.ELKOLLEN_DEMO_LOGIN === "true";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google, // reads AUTH_GOOGLE_ID and AUTH_GOOGLE_SECRET
    ...(demoLoginEnabled
      ? [
          Credentials({
            id: "demo",
            name: "Demo",
            credentials: { user: {} },
            authorize: async (input) => {
              const id = String(input?.user ?? "");
              return DEMO_USERS[id] ? { id, name: DEMO_USERS[id] } : null;
            },
          }),
        ]
      : []),
  ],
  session: { strategy: "jwt", maxAge: 60 * 60 * 8 },
  callbacks: {
    jwt({ token, account, user }) {
      if (account) {
        // The backend user id: stable per Google account, never the email address.
        token.uid =
          account.provider === "google" ? `google-${account.providerAccountId}` : user?.id;
      }
      return token;
    },
    session({ session, token }) {
      return { ...session, uid: token.uid as string | undefined };
    },
  },
});
