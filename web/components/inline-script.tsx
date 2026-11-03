// Runs during HTML parsing on a full load (before paint); inert on client renders.
// Pattern from Next's "Preventing flash before hydration" guide.
export function InlineScript({ html }: { html: string }) {
  return (
    <script
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
