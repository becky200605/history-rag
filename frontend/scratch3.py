import re

with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'r') as f:
    content = f.read()

# 1. Update the Hero background to perfectly match the application theme
old_bg = 'bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-teal-900 via-emerald-900 to-green-950'
new_bg = 'bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-[#1d4e5f] via-[#113a48] to-[#08222c]'
# Make sure we also replace bg-emerald-950
content = content.replace('bg-emerald-950', 'bg-[#0b2933]')
content = content.replace(old_bg, new_bg)

# 2. Change all the mismatched "emerald" highlights to the exact brand color [rgb(57,130,152)] -> #398298
content = content.replace('text-emerald-500', 'text-[#398298]')
content = content.replace('text-emerald-600', 'text-[#2a687a]')
content = content.replace('text-emerald-700', 'text-[#1c5061]')
content = content.replace('text-emerald-800', 'text-[#133e4d]')
content = content.replace('bg-emerald-500', 'bg-[#398298]')
content = content.replace('bg-emerald-600', 'bg-[#317487]')
content = content.replace('bg-emerald-700', 'bg-[#265e6e]')
content = content.replace('border-emerald-500', 'border-[#398298]')
content = content.replace('border-emerald-600', 'border-[#2a687a]')
content = content.replace('border-emerald-400', 'border-[#398298]/60')
content = content.replace('ring-emerald-500', 'ring-[#398298]')
content = content.replace('fill-emerald-200', 'fill-[#398298]/20')
content = content.replace('text-emerald-100', 'text-[#c6e4ec]')
content = content.replace('bg-emerald-50', 'bg-[#f0f7f9]')
content = content.replace('accent-emerald-500', 'accent-[#398298]')

# Document cover Colors: ensure they don't look completely wrong
old_cover_colors = '["bg-emerald-950", "bg-emerald-900", "bg-emerald-800", "bg-teal-950", "bg-teal-900", "bg-green-950", "bg-green-900", "bg-slate-800"]'
new_cover_colors = '["bg-[#153b47]", "bg-[#1c4756]", "bg-[#255666]", "bg-[#102d38]", "bg-[#1a3d46]", "bg-[#0b2631]", "bg-[#204a57]", "bg-[#1a3b45]"]'
content = content.replace(old_cover_colors, new_cover_colors)

# Make search box border elegant
content = content.replace(
    'shadow-lg focus-within:ring-2 focus-within:ring-[#398298]/50 transition-all border border-slate-200',
    'shadow-xl focus-within:ring-4 focus-within:ring-[#398298]/30 transition-all border border-transparent'
)

# Replace Advanced search button
content = content.replace(
    'bg-slate-700 hover:bg-slate-900 transition-colors text-white text-sm font-medium flex items-center justify-center shrink-0 hidden md:flex border-l border-slate-600',
    'bg-[#215264] hover:bg-[#1a404f] transition-colors text-white text-sm font-medium flex items-center justify-center shrink-0 hidden md:flex border-l border-[#1a404f]'
)

with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'w') as f:
    f.write(content)
print("SUCCESS: Deep teal project-matching theme applied.")

