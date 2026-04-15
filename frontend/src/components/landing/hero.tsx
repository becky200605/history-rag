"use client";

import { ChevronDown, ChevronRightIcon } from "lucide-react";
import Image from "next/image";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Hero({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "relative flex h-screen w-full flex-col items-center justify-center overflow-hidden bg-[#050505]",
        className,
      )}
    >
      {/* Background Image with Overlay */}
      <div className="absolute inset-0 z-0">
        <div className="absolute inset-0 animate-pulse-slow scale-105">
          <Image
            src="/images/landing-hero.png"
            alt="Ancient Fiscal Ledger"
            fill
            className="object-cover object-center opacity-70 transition-opacity duration-1000 grayscale-[20%]"
            priority
          />
        </div>
        {/* Complex overlays for cinematic feel and legibility */}
        <div className="absolute inset-0 bg-linear-to-r from-black/70 via-black/20 to-black/70" />
        <div className="absolute inset-0 bg-linear-to-b from-black/90 via-transparent to-black/90" />
        <div className="absolute inset-0 bg-radial-gradient from-transparent via-black/10 to-black/40" />
      </div>

      {/* Main Content Container */}
      <div className="container relative z-10 mx-auto px-6 pt-12 md:px-12">
        <div className="grid grid-cols-1 items-start gap-12 lg:grid-cols-12">
          {/* Left space reserved for the focal point of background image (ledger binding) */}
          <div className="hidden lg:col-span-4 lg:block xl:col-span-5" />

          {/* Text Content area (on the textured paper part of the background) */}
          <div className="flex flex-col justify-center py-12 lg:col-span-8 xl:col-span-7">
            <div className="flex flex-col space-y-12">
              <div className="space-y-6">
                <div className="flex items-center gap-4 animate-fade-in" style={{ animationDelay: '0.2s' }}>
                  <div className="h-px w-12 bg-[#a38a52]/50" />
                  <p className="font-serif text-sm tracking-[0.4em] text-[#a38a52] uppercase md:text-base">
                    Fiscal History Research & Analysis
                  </p>
                </div>

                <h1
                  className="animate-fade-in font-serif text-6xl leading-[1.1] text-white md:text-[5.5rem] tracking-tight"
                  style={{ animationDelay: '0.4s' }}
                >
                  财政历史 <br />
                  <span className="italic opacity-80 decoration-[#a38a52]/30 decoration-1 underline-offset-8">
                    智能知识库
                  </span>
                </h1>
              </div>

              <div
                className="animate-fade-in max-w-xl space-y-10"
                style={{ animationDelay: '0.6s' }}
              >
                <p className="font-serif text-xl leading-relaxed text-white/70 md:text-2xl md:leading-loose">
                  赋予历史文献以生命。通过大语言模型深度解析古代财政数据，
                  重构万历、康乾盛世背后的经济律动。
                  不仅仅是档案，更是跨越时空的智慧对话。
                </p>

                <div className="flex flex-wrap items-center gap-8 pt-6">
                  <Link href="/workspace">
                    <Button
                      className="group min-w-[200px] rounded-none border border-white/20 bg-white/5 px-8 py-8 font-serif text-xl text-white backdrop-blur-xl transition-all hover:bg-white/10 hover:border-[#a38a52]/60 hover:scale-105"
                      size="lg"
                    >
                      <span className="font-medium tracking-[0.3em]">
                        即刻启卷
                      </span>
                      <ChevronRightIcon className="ml-3 size-5 transition-transform group-hover:translate-x-1" />
                    </Button>
                  </Link>
                  <Button
                    variant="link"
                    className="group p-0 font-serif text-lg text-white/40 transition-colors hover:text-white"
                  >
                    探索技术细节
                    <span className="ml-2 transition-opacity opacity-0 group-hover:opacity-100">
                      →
                    </span>
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* Small Vertical Indicator on the right edge */}
          <div className="fixed right-12 top-1/2 hidden -translate-y-1/2 flex-col items-center gap-16 xl:flex">
            <div className="h-32 w-px bg-linear-to-b from-transparent via-[#a38a52]/30 to-transparent" />
            <div
              className="font-serif text-xl tracking-[0.6em] text-[#a38a52]/60"
              style={{ writingMode: "vertical-rl" }}
            >
              道光三十年 · 粮食存余
            </div>
            <div className="flex flex-col gap-4">
              {[1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className={cn(
                    "size-1.5 rounded-full transition-all duration-700",
                    i === 1
                      ? "bg-[#a38a52] scale-125 shadow-[0_0_12px_rgba(163,138,82,0.8)]"
                      : "bg-white/10",
                  )}
                />
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Footer Info / Scroll Indicator */}
      <div className="absolute bottom-12 z-10 w-full px-12 md:px-20">
        <div className="flex flex-col items-center justify-between gap-8 border-t border-white/5 pt-10 md:flex-row">
          <div className="flex gap-12 font-serif text-[10px] tracking-[0.3em] text-white/20 uppercase">
            <span>ARCHIVE NO. 2026-FH01</span>
            <span>TIMESTAMP: 2026.04.16</span>
          </div>

          <div className="flex flex-col items-center gap-4">
            <div className="animate-bounce-slow">
              <ChevronDown className="size-6 text-white/20" />
            </div>
            <span className="font-serif text-[10px] tracking-[0.6em] text-white/10 uppercase">
              Scroll to explore
            </span>
          </div>

          <div className="hidden font-serif text-[10px] tracking-[0.3em] text-white/20 uppercase md:block">
            © 2026 Fiscal History Research Lab
          </div>
        </div>
      </div>
    </div>
  );
}
