import re

with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'r') as f:
    content = f.read()

# 1. Update Hero Background Color & Shape
# "bg-slate-800 shrink-0 w-full"
# "bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-slate-700 via-slate-800 to-slate-900"
content = content.replace(
    'bg-slate-800 shrink-0 w-full',
    'bg-emerald-950 shrink-0 w-full'
)
content = content.replace(
    'bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-slate-700 via-slate-800 to-slate-900',
    'bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-teal-900 via-emerald-900 to-green-950'
)

# 2. Modify container layout width
# "max-w-[1200px] mx-auto w-full px-6 py-8"
# We'll make it completely w-full to be "平铺"
content = content.replace(
    '<div className="max-w-[1200px] mx-auto w-full px-6 py-8">',
    '<div className="w-full px-8 py-8 md:px-12">'
)
# Make the wrapper div bg-white instead of #fafafa? Actually standard bg is usually #fafafa or #f8fafc. 
content = content.replace(
    'bg-[#fafafa]',
    'bg-white sm:shadow-inner'
)
# Remove inner card border (wait we didn't have outer card border, but we can make the file cards themselves less stark, but user said "最外侧不用卡片布局", so WorkspaceContainer is already omitted, it should be fine).

# 3. Replace color tokens
# We want to replace all 'blue-' with 'emerald-' in our injected section, but carefully.
# We'll only target the specific Tailwind classes in our section.
for hue in ['50', '100', '200', '300', '400', '500', '600', '700', '800', '900']:
    content = content.replace(f'text-blue-{hue}', f'text-emerald-{hue}')
    content = content.replace(f'bg-blue-{hue}', f'bg-emerald-{hue}')
    content = content.replace(f'border-blue-{hue}', f'border-emerald-{hue}')
    content = content.replace(f'ring-blue-{hue}', f'ring-emerald-{hue}')
    content = content.replace(f'fill-blue-{hue}', f'fill-emerald-{hue}')
    content = content.replace(f'accent-blue-{hue}', f'accent-emerald-{hue}')

# 4. Replace the hardcoded tags below the search bar
old_tags_code = """                 {/* Summary / Filters matching reference */}
                 <div className="flex items-center gap-6 mt-5 px-2 w-full overflow-x-auto text-sm text-slate-300 select-none">
                    {["所有文件", "图书文献", "报纸刊物", "机密档案", "期刊杂志", "视听资料", "图片专栏", "专题汇编"].map((tag, idx) => (
                       <label key={idx} className="flex items-center gap-1.5 cursor-pointer hover:text-white transition-colors">
                         <input type="checkbox" className="accent-emerald-500 size-3.5" defaultChecked={idx === 0} />
                         {tag}
                       </label>
                    ))}
                 </div>"""

new_tags_code = """                 {/* Dynamic folder tags matching reference */}
                 <div className="flex items-center gap-6 mt-5 px-2 w-full overflow-x-auto text-sm text-emerald-100/70 select-none">
                    <label className="flex items-center gap-1.5 cursor-pointer hover:text-white transition-colors">
                      <input type="checkbox" className="accent-emerald-500 size-3.5" checked={selectedFolderPath === "all"} onChange={() => setSelectedFolderPath("all")} />
                      全部
                    </label>
                    {systemFolderTree.map((folderNode, idx) => (
                       <label key={folderNode.path} className="flex items-center gap-1.5 cursor-pointer hover:text-white transition-colors">
                         <input type="checkbox" className="accent-emerald-500 size-3.5" checked={selectedFolderPath === folderNode.path || selectedFolderPath.startsWith(folderNode.path)} onChange={() => setSelectedFolderPath(folderNode.path)} />
                         {folderNode.name}
                       </label>
                    ))}
                 </div>"""

content = content.replace(old_tags_code, new_tags_code)

# Let's also update the Document cover Colors to be all shades of green
old_cover_colors = '["bg-red-900", "bg-emerald-900", "bg-emerald-900", "bg-amber-900", "bg-purple-900", "bg-teal-900", "bg-indigo-900", "bg-slate-800"]'
new_cover_colors = '["bg-emerald-950", "bg-emerald-900", "bg-emerald-800", "bg-teal-950", "bg-teal-900", "bg-green-950", "bg-green-900", "bg-slate-800"]'
content = content.replace(old_cover_colors, new_cover_colors)

with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'w') as f:
    f.write(content)
print("SUCCESS: Colors and layouts updated")

