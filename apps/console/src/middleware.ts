import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PREFIXES = [
  "/",
  "/docs",
  "/design-system",
  "/mock-artifacts",
  "/favicon.ico",
];

function isPublicPath(pathname: string): boolean {
  if (pathname === "/") return true;
  return PUBLIC_PREFIXES.some(
    (prefix) => prefix !== "/" && pathname.startsWith(prefix),
  );
}

export function middleware(request: NextRequest) {
  if (process.env.PROMPTETHEUS_REQUIRE_CONSOLE_AUTH !== "1") {
    return NextResponse.next();
  }
  if (isPublicPath(request.nextUrl.pathname)) {
    return NextResponse.next();
  }

  const hasSupabaseSession = request.cookies
    .getAll()
    .some((cookie) => cookie.name.startsWith("sb-"));
  if (hasSupabaseSession) {
    return NextResponse.next();
  }

  // API routes must answer with JSON so client fetch()s surface a real error
  // instead of trying to JSON.parse the redirected HTML sign-in page
  // ("Unexpected token '<', \"<!DOCTYPE\"...").
  if (request.nextUrl.pathname.startsWith("/api/")) {
    return NextResponse.json(
      { error: "Console authentication required. Sign in to continue." },
      { status: 401 },
    );
  }

  const url = request.nextUrl.clone();
  url.pathname = "/";
  url.searchParams.set("auth", "required");
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
