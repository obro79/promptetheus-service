import { NextResponse } from "next/server";

export const runtime = "nodejs";

const TARGET_REPO = "obro79/demo-agents";

export async function GET(
  _request: Request,
  { params }: { params: { path: string[] } },
) {
  if (!enabled()) return notFound();

  const path = params.path.join("/");
  if (path === `repos/${TARGET_REPO}/git/ref/heads/main`) {
    return NextResponse.json({ object: { sha: "e2e-main-sha" } });
  }
  if (path.startsWith(`repos/${TARGET_REPO}/contents/`)) {
    return NextResponse.json({
      content: Buffer.from("Promptetheus E2E mock file\n", "utf8").toString("base64"),
      encoding: "base64",
      sha: "e2e-file-sha",
    });
  }

  return notFound();
}

export async function POST(
  request: Request,
  { params }: { params: { path: string[] } },
) {
  if (!enabled()) return notFound();

  const path = params.path.join("/");
  if (path === `repos/${TARGET_REPO}/git/refs`) {
    return NextResponse.json({ ref: "refs/heads/e2e" });
  }
  if (path === `repos/${TARGET_REPO}/pulls`) {
    const body = (await request.json()) as { title?: string; head?: string };
    const number = pullNumber(body.title ?? body.head ?? "");
    return NextResponse.json({
      html_url: `https://github.com/${TARGET_REPO}/pull/${number}`,
      number,
    });
  }
  if (/^repos\/obro79\/demo-agents\/issues\/\d+\/comments$/.test(path)) {
    return NextResponse.json({ id: 9001 });
  }

  return notFound();
}

export async function PUT(
  _request: Request,
  { params }: { params: { path: string[] } },
) {
  if (!enabled()) return notFound();

  const path = params.path.join("/");
  if (path.startsWith(`repos/${TARGET_REPO}/contents/`)) {
    return NextResponse.json({ content: { sha: "e2e-updated-file-sha" } });
  }

  return notFound();
}

export async function PATCH(
  request: Request,
  { params }: { params: { path: string[] } },
) {
  if (!enabled()) return notFound();

  const path = params.path.join("/");
  if (/^repos\/obro79\/demo-agents\/pulls\/\d+$/.test(path)) {
    const body = (await request.json()) as { state?: string };
    return NextResponse.json({ state: body.state ?? "closed" });
  }

  return notFound();
}

function enabled(): boolean {
  return process.env.PROMPTETHEUS_E2E_GITHUB_MOCK === "1";
}

function notFound() {
  return NextResponse.json({ message: "Not Found" }, { status: 404 });
}

function pullNumber(value: string): number {
  const lower = value.toLowerCase();
  if (lower.includes("browser")) return 91;
  if (lower.includes("chat")) return 92;
  if (lower.includes("voice")) return 93;
  if (lower.includes("test")) return 94;
  return 90;
}
