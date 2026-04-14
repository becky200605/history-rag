import re

with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'r') as f:
    content = f.read()

# Remove 高级检索
content = re.sub(
    r'<button\s+className="h-full px-5 bg-\[#215264\].*?高级检索\s*</button>',
    '',
    content,
    flags=re.DOTALL
)

# Update the checkboxes
old_checkboxes = """                 {/* Dynamic folder tags matching reference */}
                 <div className="flex items-center gap-6 mt-5 px-2 w-full overflow-x-auto text-sm text-[#c6e4ec]/70 select-none">
                    <label className="flex items-center gap-1.5 cursor-pointer hover:text-white transition-colors">
                      <input type="checkbox" className="accent-[#398298] size-3.5" checked={selectedFolderPath === "all"} onChange={() => setSelectedFolderPath("all")} />
                      全部
                    </label>
                    {systemFolderTree.map((folderNode, idx) => (
                       <label key={folderNode.path} className="flex items-center gap-1.5 cursor-pointer hover:text-white transition-colors">
                         <input type="checkbox" className="accent-[#398298] size-3.5" checked={selectedFolderPath === folderNode.path || selectedFolderPath.startsWith(folderNode.path)} onChange={() => setSelectedFolderPath(folderNode.path)} />
                         {folderNode.name}
                       </label>
                    ))}
                 </div>"""

new_checkboxes = """                 {/* Dynamic folder tags matching reference */}
                 <div className="flex items-center gap-8 mt-6 px-1 w-full overflow-x-auto select-none">
                    <label className="flex items-center gap-2 cursor-pointer group">
                      <div className="relative flex items-center justify-center">
                        <input type="checkbox" className="peer appearance-none w-4 h-4 border-2 border-[#2b6475] rounded-sm bg-[#08222c]/50 checked:bg-[#398298] checked:border-[#398298] transition-colors cursor-pointer" checked={selectedFolderPath === "all"} onChange={() => setSelectedFolderPath("all")} />
                        <svg className="absolute w-3 h-3 text-white pointer-events-none opacity-0 peer-checked:opacity-100 transition-opacity" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                      </div>
                      <span className="text-[14px] font-medium text-[#98c5d3] group-hover:text-white transition-colors tracking-wide pt-0.5">全部</span>
                    </label>
                    {systemFolderTree.map((folderNode, idx) => (
                       <label key={folderNode.path} className="flex items-center gap-2 cursor-pointer group">
                         <div className="relative flex items-center justify-center">
                           <input type="checkbox" className="peer appearance-none w-4 h-4 border-2 border-[#2b6475] rounded-sm bg-[#08222c]/50 checked:bg-[#398298] checked:border-[#398298] transition-colors cursor-pointer" checked={selectedFolderPath === folderNode.path || selectedFolderPath.startsWith(folderNode.path)} onChange={() => setSelectedFolderPath(folderNode.path)} />
                           <svg className="absolute w-3 h-3 text-white pointer-events-none opacity-0 peer-checked:opacity-100 transition-opacity" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                         </div>
                         <span className="text-[14px] font-medium text-[#98c5d3] group-hover:text-white transition-colors tracking-wide pt-0.5">{folderNode.name}</span>
                       </label>
                    ))}
                 </div>"""

content = content.replace(old_checkboxes, new_checkboxes)

# Enhance Hero Pattern
old_pattern = '<div className="absolute inset-0 opacity-20 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-[#1d4e5f] via-[#113a48] to-[#08222c] pointer-events-none"></div>'
new_pattern = """{/* Premium Hero Background with subtle grid/texture */}
               <div className="absolute inset-0 bg-[#081d24]"></div>
               <div className="absolute inset-0 opacity-60 bg-[radial-gradient(circle_at_top_right,_var(--tw-gradient-stops))] from-[#235b6b] via-[#0b2831] to-transparent pointer-events-none"></div>
               <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "url(\\\"data:image/svg+xml,%3Csvg width='24' height='24' viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M0 0h24v24H0V0zm1 1h22v22H1V1zm2 2h18v18H3V3z' fill='%23ffffff' fill-rule='evenodd'/%3E%3C/svg%3E\\\")", backgroundSize: "24px 24px" }}></div>"""
content = content.replace(old_pattern, new_pattern)

# Also fix the inner padding of the Input so it matches the Search button better
# And change Search Button to primary #398298 so it pops
content = content.replace('<button className="h-full px-8 bg-[#2a687a] hover:bg-[#317487] transition-colors text-white flex items-center justify-center shrink-0">',
                          '<button className="h-full px-10 bg-[#398298] hover:bg-[#2c687a] transition-colors text-white flex items-center justify-center shrink-0 shadow-inner">')

# Modify the Top Right Management Buttons
# We want them to look premium, not cheap transparent borders.
content = content.replace('className="bg-white/10 text-white border-white/20 hover:bg-white/20 hover:text-white h-8 text-xs"',
                          'className="bg-black/20 text-white/90 border-white/10 hover:bg-white/10 hover:text-white h-8 text-xs backdrop-blur-sm shadow-sm"')
content = content.replace('className="bg-white/10 text-white border-white/20 hover:bg-white/20 hover:text-white h-8 text-xs px-2"',
                          'className="bg-black/20 text-white/90 border-white/10 hover:bg-white/10 hover:text-white h-8 text-xs px-2 backdrop-blur-sm shadow-sm"')

# Search Box wrapper: drop the rounded-md for a rounded-full or softer rounded-lg? The reference screenshot had it pill-shaped. Oh wait! In the screenshot, it did NOT look pill shaped. Let's make it rounded-lg to be safe.
content = content.replace('<div className="flex bg-white rounded-md overflow-hidden h-14 shadow-xl focus-within:ring-4 focus-within:ring-[#398298]/30 transition-all border border-transparent">',
                          '<div className="flex bg-white rounded-lg overflow-hidden h-[60px] shadow-2xl focus-within:ring-[3px] focus-within:ring-[#398298]/50 transition-all border border-white/10">')

with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'w') as f:
    f.write(content)
print("SUCCESS: UI visually enhanced.")

