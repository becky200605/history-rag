import { useMemo } from "react";

export function Footer() {
  const year = useMemo(() => new Date().getFullYear(), []);
  return (
    <footer className="container-md mx-auto mt-32 flex flex-col items-center justify-center">
      <hr className="from-border/0 to-border/0 m-0 h-px w-full border-none bg-linear-to-r via-white/20" />
      <div className="text-muted-foreground container mb-8 flex flex-col items-center justify-center text-xs">
        <p>华中师范大学</p>
        <p>&copy; {year} 财政历史智能知识库</p>
      </div>
    </footer>
  );
}
