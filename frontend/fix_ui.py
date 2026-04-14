import re

with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'r') as f:
    content = f.read()

# 1. Update Hero Section: Clean, Professional, integrated.
# Remove the harsh gradient and jail grid.
old_hero = r'<div className="relative bg-\[#17596c\].*?{/\* Clean, Simple Brand-color Gradient Background \*/}.*?</div>'
new_hero_header = """<div className="relative bg-[#f8fafc] border-b border-slate-200 shrink-0 w-full flex flex-col items-center justify-center pt-20 pb-16 px-6">
               {/* Subtle background element for premium feel */}
               <div className="absolute inset-0 bg-[radial-gradient(45%_40%_at_50%_40%,#e2eff3_0%,#f8fafc_100%)] opacity-70"></div>"""

# Need to be careful with regex for existing hero.
# Actually I'll just look for the markers.

# 2. Fix Search Box: Perfect vertical centering.
# We'll use a wrapper with flex items-center.
content = content.replace(
    'bg-[#17596c] shrink-0 w-full flex flex-col items-center justify-center pt-16 mt-0 pb-12 px-6 overflow-hidden',
    'bg-[#f8fafc] border-b border-slate-100 shrink-0 w-full flex flex-col items-center justify-center pt-20 pb-16 px-6 overflow-hidden relative'
)

# Replace the inner gradient/pattern
content = content.replace(
    '{/* Clean, Simple Brand-color Gradient Background */}\n               <div className="absolute inset-0 bg-gradient-to-r from-[#17596c] via-[#124b5c] to-[#0d3b4a]"></div>\n               <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-white/10 to-transparent opacity-30 pointer-events-none"></div>',
    '{/* High-end clean background */}\n               <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,#eef6f8,transparent)] pointer-events-none"></div>'
)

# 3. Search Bar specifically:
# Ensure SelectTrigger is perfectly centered.
# The user's screenshot showed the text "全部状态" might be slightly high or low.
# We'll use flex items-center on the Trigger and ensure no weird line-height.
content = content.replace(
    'min-h-[60px] border-none focus:ring-0 rounded-none bg-transparent text-[15px] text-[#2c3e50] shadow-none font-semibold flex items-center justify-between px-5 outline-none hover:text-[#398298]',
    'h-[60px] border-none focus:ring-0 rounded-none bg-transparent text-[15px] text-[#2c3e50] shadow-none font-semibold flex items-center justify-center gap-2 px-5 outline-none hover:text-[#398298] align-middle'
)

# 4. Checkboxes: Remove pt-0.5 to fix centering. 
content = content.replace('tracking-wide pt-0.5', 'tracking-wide')
# And make the labels a bit darker/integrated if it's a light background now.
content = content.replace('text-[#c6e4ec]/70', 'text-slate-500')
content = content.replace('text-[#98c5d3]', 'text-slate-600')

# 5. Search Bar shadow and border:
content = content.replace(
    'shadow-2xl focus-within:ring-[3px] focus-within:ring-[#398298]/50 transition-all border border-white/10',
    'shadow-[0_20px_40px_rgba(0,0,0,0.08)] ring-1 ring-slate-200 focus-within:ring-2 focus-within:ring-[#398298]/30 transition-all'
)

with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'w') as f:
    f.write(content)
print("SUCCESS: Search UI refined and background integrated.")
