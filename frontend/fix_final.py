import re

with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'r') as f:
    content = f.read()

# 1. Replace the checkbox/tags area for perfect alignment
old_tags_pattern = r'<div className="flex items-center gap-8 mt-6 px-1 w-full overflow-x-auto select-none">.*?</div>'
new_tags_code = """<div className="flex items-center gap-10 mt-6 px-1 w-full overflow-x-auto select-none">
                    <label className="flex items-center gap-2.5 cursor-pointer group">
                      <div className="relative flex items-center justify-center">
                        <input type="checkbox" className="peer appearance-none w-4 h-4 border-2 border-[#398298]/30 rounded-sm bg-white checked:bg-[#398298] checked:border-[#398298] transition-all cursor-pointer" checked={selectedFolderPath === "all"} onChange={() => setSelectedFolderPath("all")} />
                        <svg className="absolute w-3 h-3 text-white pointer-events-none opacity-0 peer-checked:opacity-100 transition-opacity" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                      </div>
                      <span className="text-[14px] font-semibold text-slate-500 group-hover:text-[#398298] transition-colors tracking-wide leading-none">全部资源</span>
                    </label>
                    {systemFolderTree.map((folderNode) => (
                       <label key={folderNode.path} className="flex items-center gap-2.5 cursor-pointer group">
                         <div className="relative flex items-center justify-center">
                           <input type="checkbox" className="peer appearance-none w-4 h-4 border-2 border-[#398298]/30 rounded-sm bg-white checked:bg-[#398298] checked:border-[#398298] transition-all cursor-pointer" checked={selectedFolderPath === folderNode.path || selectedFolderPath.startsWith(folderNode.path)} onChange={() => setSelectedFolderPath(folderNode.path)} />
                           <svg className="absolute w-3 h-3 text-white pointer-events-none opacity-0 peer-checked:opacity-100 transition-opacity" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                         </div>
                         <span className="text-[14px] font-semibold text-slate-500 group-hover:text-[#398298] transition-colors tracking-wide leading-none">{folderNode.name}</span>
                       </label>
                    ))}
                  </div>"""

content = re.sub(old_tags_pattern, new_tags_code, content, flags=re.DOTALL)

# 2. Replace the breadcrumb row with the new Toolbar row
old_breadcrumb_pattern = r'<div className="flex justify-between items-center mb-6 bg-white py-3 border-b border-slate-100 sticky top-0 z-20">.*?</div>'
new_toolbar_code = """<div className="flex justify-between items-center mb-8 px-5 py-5 bg-white rounded-2xl border border-[#398298]/10 shadow-[0_2px_15px_rgba(57,130,152,0.03)]">
                     <div className="flex items-center gap-2 text-[15px] font-medium">
                        <button className="text-slate-400 hover:text-[#398298] transition-colors" onClick={() => setSelectedFolderPath("all")}>
                           全部馆藏
                        </button>
                        {breadcrumbs.map((bc) => (
                            <React.Fragment key={bc.path}>
                              <ChevronRightIcon className="size-4 text-slate-300" />
                              <button className="text-slate-700 hover:text-[#398298] transition-colors" onClick={() => setSelectedFolderPath(bc.path)}>
                                {bc.name === "系统" ? "系统知识库" : bc.name === "个人" ? "个人空间" : bc.name}
                              </button>
                            </React.Fragment>
                        ))}
                     </div>
                     
                     <div className="flex items-center gap-4">
                        <div className="flex items-center bg-slate-50 p-1 rounded-lg border border-slate-100">
                          <Button variant="ghost" size="sm" className="h-8 px-4 text-[#398298] hover:bg-white hover:shadow-sm transition-all" onClick={handleOpenUploadDialog} disabled={uploadMutation.isPending || uploadUserMutation.isPending}>
                             {uploadMutation.isPending || uploadUserMutation.isPending ? <Loader2Icon className="size-3.5 animate-spin mr-1.5" /> : <PlusIcon className="size-3.5 mr-1.5" />}
                             上传档案
                          </Button>
                          <Button variant="ghost" size="sm" className="h-8 px-4 text-slate-600 hover:bg-white hover:text-[#398298] hover:shadow-sm transition-all" onClick={() => setIsCreateFolderDialogOpen(true)} disabled={createSpaceMutation.isPending}>
                             <FolderIcon className="size-3.5 mr-1.5" />
                             新建分区
                          </Button>
                        </div>
                        
                        <div className="h-6 w-[1px] bg-slate-200 mx-1"></div>
                        
                        <Button variant="outline" size="sm" className="h-9 gap-1.5 border-[#398298]/20 bg-white text-[#398298] hover:bg-[#398298] hover:text-white transition-all shadow-sm" onClick={handleStartChat} disabled={selectedRowIds.length === 0}>
                          <BookmarkPlusIcon className="size-4" />
                          <span className="text-sm font-semibold text-inherit">引用提问 ({selectedRowIds.length})</span>
                        </Button>
                        
                        <button 
                           className="flex items-center gap-1.5 text-slate-400 hover:text-[#398298] transition-colors text-[13px] font-medium ml-2"
                           onClick={handleToggleAllVisible}
                        >
                           {allVisibleSelected ? <CheckSquareIcon className="size-4 text-[#398298]" /> : <SquareIcon className="size-4" />}
                           <span>本页全选</span>
                        </button>
                     </div>
                   </div>"""

content = re.sub(old_breadcrumb_pattern, new_toolbar_code, content, flags=re.DOTALL)

# 3. Final touch: Search Button color was still emerald in code but we need brand teal
content = content.replace('bg-[#265e6e] hover:bg-emerald-800', 'bg-[#398298] hover:bg-[#2c6a7a]')

with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'w') as f:
    f.write(content)
print("SUCCESS: UI Refined and aligned.")
