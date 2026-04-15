"use client";

import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import { motion } from "motion/react";

import { Button } from "@/components/ui/button";
import { SilkRibbon } from "@/components/workspace/silk-ribbon";
import { cn } from "@/lib/utils";

export function Hero({ className }: { className?: string }) {
  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.3,
      },
    },
  };

  const itemVariants = {
    hidden: { opacity: 0, filter: "blur(10px)", y: 20 },
    visible: { 
      opacity: 1, 
      filter: "blur(0px)", 
      y: 0,
      transition: { duration: 1.2, ease: [0.22, 1, 0.36, 1] }
    },
  };

  return (
    <div
      className={cn(
        "relative flex h-screen w-full flex-col items-center justify-center overflow-hidden bg-background",
        className,
      )}
    >
      {/* Background decoration - optional subtle gradient or just clean */}
      <div className="absolute inset-0 z-0 opacity-[0.03] pointer-events-none">
        <div className="absolute inset-0 bg-radial-gradient from-primary via-transparent to-transparent" />
      </div>

      {/* Main Content Container */}
      <motion.div 
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="container relative z-10 mx-auto flex flex-col items-center px-6 text-center"
      >
        <motion.div variants={itemVariants} className="space-y-8">
          <h1 className="font-serif text-6xl font-bold tracking-[0.1em] text-foreground md:text-[5rem]">
            财政历史 <br />
            <span className="text-primary italic opacity-90">智能知识库</span>
          </h1>
          
          <div className="mx-auto h-px w-24 bg-primary/30" />
        </motion.div>

        <motion.div variants={itemVariants} className="pt-12">
          <Link href="/workspace">
            <Button
              className="group relative min-w-[240px] overflow-hidden rounded-full border border-primary/20 bg-primary/5 px-10 py-8 font-serif text-2xl text-primary backdrop-blur-md transition-all hover:bg-primary hover:text-white hover:scale-105"
              size="lg"
            >
              <span className="relative z-10 font-medium tracking-[0.2em]">
                即刻启卷
              </span>
              <ChevronRightIcon className="relative z-10 ml-3 size-6 transition-transform group-hover:translate-x-1" />
              
              {/* Button hover effect mask */}
              <div className="absolute inset-0 -translate-x-full bg-linear-to-r from-transparent via-white/10 to-transparent transition-transform duration-500 group-hover:translate-x-full" />
            </Button>
          </Link>
        </motion.div>
      </motion.div>

      {/* Unified Silk Ribbon Footer Decoration */}
      <SilkRibbon />
    </div>
  );
}
