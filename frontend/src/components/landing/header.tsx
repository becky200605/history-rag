import Link from "next/link";

import { Button } from "@/components/ui/button";

export function Header() {
  return (
    <header className="fixed top-0 right-0 left-0 z-20 mx-auto flex h-24 items-center justify-between px-12 transition-all duration-500">
      <div className="flex items-center gap-4">
        <Link href="/" className="group flex items-center gap-3">
          <div className="size-8 border border-[#a38a52]/40 bg-[#a38a52]/5 transition-colors group-hover:bg-[#a38a52]/10 flex items-center justify-center">
            <span className="font-serif text-[#a38a52] text-xs">FH</span>
          </div>
          <h1 className="font-serif text-lg tracking-[0.2em] text-white/80 transition-colors group-hover:text-white uppercase">
            Fiscal History Lab
          </h1>
        </Link>
      </div>
      
      <div className="flex items-center gap-8">
        <nav className="hidden md:flex items-center gap-8 pr-8 border-r border-white/5">
           {['Archives', 'Methodology', 'Library', 'Contact'].map((item) => (
             <Link key={item} href="#" className="font-serif text-[10px] tracking-[0.3em] text-white/30 hover:text-white transition-colors uppercase">
               {item}
             </Link>
           ))}
        </nav>
        <Button asChild variant="ghost" className="rounded-none border border-white/10 font-serif text-xs tracking-widest text-white/60 hover:bg-white/5 hover:text-white hover:border-white/30">
          <Link href="/auth">LOGIN / JOIN</Link>
        </Button>
      </div>
    </header>
  );
}
