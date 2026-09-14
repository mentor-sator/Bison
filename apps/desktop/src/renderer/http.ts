export async function request(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new Error(`nothing answered at ${new URL(url).origin}`);
  }
}
