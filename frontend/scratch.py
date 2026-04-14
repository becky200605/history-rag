import re

with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'r') as f:
    content = f.read()

start_marker = r'            {/\* Windows 11 Explorer Style Toolbar \(Ribbon\) \*/}'
# Match until the </section> after the big conditional
end_marker = r'          </section>'

replacement = """            {/* HERO SEARCH BANNER */}
            <div className="relative bg-slate-800 shrink-0 w-full flex flex-col items-center justify-center pt-16 mt-0 pb-12 px-6 overflow-hidden">
               {/* Pattern overlay for digital library feel */}
               <div className="absolute inset-0 opacity-20 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-slate-700 via-slate-800 to-slate-900 pointer-events-none"></div>
               
               {/* Global Management Actions (Top Right) */}
               <div className="absolute top-4 right-4 flex items-center gap-2 z-20">
                 <Button variant="outline" size="sm" className="bg-white/10 text-white border-white/20 hover:bg-white/20 hover:text-white h-8 text-xs" onClick={handleOpenUploadDialog} disabled={uploadMutation.isPending || uploadUserMutation.isPending}>
                   {uploadMutation.isPending || uploadUserMutation.isPending ? <Loader2Icon className="size-3.5 animate-spin mr-1.5" /> : <UploadIcon className="size-3.5 mr-1.5" />}
                   上传档案
                 </Button>
                 <Button variant="outline" size="sm" className="bg-white/10 text-white border-white/20 hover:bg-white/20 hover:text-white h-8 text-xs" onClick={() => setIsCreateFolderDialogOpen(true)} disabled={createSpaceMutation.isPending}>
                   <FolderIcon className="size-3.5 mr-1.5" />
                   新建分区
                 </Button>
                 <Button variant="outline" size="sm" className="bg-white/10 text-white border-white/20 hover:bg-white/20 hover:text-white h-8 text-xs px-2" onClick={() => void refetch()} disabled={isFetching}>
                   <RefreshCwIcon className={cn("size-3.5", isFetching && "animate-spin")} />
                 </Button>
               </div>

               {/* Central Hero Elements */}
               <div className="max-w-4xl w-full z-10">
                 <div className="flex bg-white rounded-md overflow-hidden h-14 shadow-lg focus-within:ring-2 focus-within:ring-blue-500/50 transition-all border border-slate-200">
                    {/* Status Dropdown acting as Search Scope */}
                    <div className="border-r border-slate-200 bg-slate-50 relative hidden sm:block w-[130px] shrink-0">
                      <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as FileStatusFilter)}>
                          <SelectTrigger className="h-full w-full border-none focus:ring-0 rounded-none bg-transparent text-sm text-slate-700 shadow-none font-medium text-center pl-4">
                            <SelectValue placeholder="检索范围" />
                          </SelectTrigger>
                          <SelectContent>
                            {statusFilterOptions.map((option) => (
                              <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                            ))}
                          </SelectContent>
                      </Select>
                    </div>
                    {/* Actual Search Input */}
                    <Input
                      value={searchQuery}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      placeholder="请输入文献、档案或书籍名称进行检索..."
                      className="flex-1 h-full border-none rounded-none outline-none focus-visible:ring-0 text-base px-5 shadow-none text-slate-800 placeholder:text-slate-400"
                    />
                    {/* Search Button */}
                    <button className="h-full px-8 bg-blue-700 hover:bg-blue-800 transition-colors text-white flex items-center justify-center shrink-0">
                      <SearchIcon className="size-5" />
                    </button>
                    <button className="h-full px-5 bg-slate-700 hover:bg-slate-900 transition-colors text-white text-sm font-medium flex items-center justify-center shrink-0 hidden md:flex border-l border-slate-600">
                      高级检索
                    </button>
                 </div>
                 
                 {/* Summary / Filters matching reference */}
                 <div className="flex items-center gap-6 mt-5 px-2 w-full overflow-x-auto text-sm text-slate-300 select-none">
                    {["所有文件", "图书文献", "报纸刊物", "机密档案", "期刊杂志", "视听资料", "图片专栏", "专题汇编"].map((tag, idx) => (
                       <label key={idx} className="flex items-center gap-1.5 cursor-pointer hover:text-white transition-colors">
                         <input type="checkbox" className="accent-blue-500 size-3.5" defaultChecked={idx === 0} />
                         {tag}
                       </label>
                    ))}
                 </div>
               </div>
            </div>

            {/* Main Workspace (Scrollable) */}
            <div className="flex-1 overflow-y-auto bg-[#fafafa]">
               <div className="max-w-[1200px] mx-auto w-full px-6 py-8">
               
                   {/* Address Bar / Breadcrumbs */}
                   <div className="flex justify-between items-center mb-6">
                     <div className="flex items-center gap-2 text-[15px] text-slate-600 font-medium">
                        <button className="hover:text-blue-600 transition-colors flex items-center gap-1.5" onClick={() => setSelectedFolderPath("all")}>
                          <span className="text-blue-600 font-bold">全部馆藏</span>
                        </button>
                        {breadcrumbs.map((bc) => (
                            <React.Fragment key={bc.path}>
                              <ChevronRightIcon className="size-4 text-slate-400" />
                              <button className="hover:text-blue-600 transition-colors font-medium border-b border-transparent hover:border-blue-600" onClick={() => setSelectedFolderPath(bc.path)}>
                                {bc.name === "系统" ? "系统知识库" : bc.name === "个人" ? "个人空间" : bc.name}
                              </button>
                            </React.Fragment>
                        ))}
                     </div>
                     
                     <div className="flex items-center gap-3">
                        <Button variant="outline" size="sm" className="h-8 gap-1.5 text-slate-600 bg-white border-slate-300 hover:bg-blue-50 hover:text-blue-700 transition-colors" onClick={handleStartChat} disabled={selectedRowIds.length === 0}>
                          <BookmarkPlusIcon className="size-4" />
                          <span className="text-sm font-medium">基于选择片段提问 ({selectedRowIds.length})</span>
                        </Button>
                        <button 
                           className="flex items-center gap-1.5 text-slate-500 hover:text-blue-600 transition-colors text-sm font-medium ml-2"
                           onClick={handleToggleAllVisible}
                        >
                           {allVisibleSelected ? <CheckSquareIcon className="size-4 outline-none text-blue-600" /> : <SquareIcon className="size-4 outline-none" />}
                           <span>全选本页</span>
                        </button>
                     </div>
                   </div>

                   {isLoading || personalRecordsQuery.isLoading || personalSpacesQuery.isLoading ? (
                      <div className="flex flex-col items-center justify-center py-20 text-slate-500">
                        <Loader2Icon className="size-8 animate-spin text-blue-500 mb-4" />
                        正在检索文献馆藏...
                      </div>
                   ) : error || personalRecordsQuery.error || personalSpacesQuery.error ? (
                      <div className="m-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-600 shadow-sm">
                        {(error ?? personalRecordsQuery.error ?? personalSpacesQuery.error)?.message}
                      </div>
                   ) : (
                     <div className="flex flex-col">
                       {/* Folder Grid Buttons */}
                       {currentLevelFolderNodes.length > 0 && (
                         <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4 mb-10">
                            {currentLevelFolderNodes.map(folder => (
                               <button 
                                 key={folder.path}
                                 onClick={() => setSelectedFolderPath(folder.path)}
                                 className="flex items-center gap-3 bg-[#fdfdfd] border border-slate-200/80 p-4 rounded-md shadow-[0_1px_2px_rgba(0,0,0,0.02)] hover:shadow-md hover:border-blue-400 hover:bg-blue-50/50 transition-all text-slate-700 group text-left"
                               >
                                  <div className="size-10 shrink-0 rounded bg-amber-50 border border-amber-100 flex items-center justify-center group-hover:bg-amber-100 transition-colors">
                                    <FolderIcon className="size-5 text-amber-500 fill-amber-200" />
                                  </div>
                                  <span className="text-[15px] font-semibold text-slate-800 tracking-wide truncate w-full group-hover:text-blue-700 transition-colors">
                                    {folder.name === "系统" ? "系统知识库" : folder.name === "个人" ? "个人空间" : folder.name}
                                  </span>
                               </button>
                            ))}
                         </div>
                       )}

                       {/* Document Cards */}
                       {folderFilteredFiles.length > 0 ? (
                          <div className="flex flex-col gap-6 pb-16">
                            {folderFilteredFiles.map(file => {
                              const isSelected = selectedRowIds.includes(file.rowId);
                              const canSelectForChat = Boolean(file.docId) && file.parseStatus === "indexed";
                              const readerHref = buildManagedFileReaderHref(file);
                              const canOpenReader = Boolean(readerHref) && Boolean(file.documentUrl) && ["indexed", "parsed"].includes(file.parseStatus ?? "");
                              const isDeleting = (file.source === "global" && deleteMutation.isPending && deletingFilename === file.filename) || (file.source === "personal" && deleteUserRecordMutation.isPending && deletingRecordId === file.userRecordId);
                              const isRetrying = retryMutation.isPending && retryingFilename === file.filename;
                              const canRetry = file.source === "global" && file.indexable && ["failed", "index_failed", "indexed"].includes(file.parseStatus ?? "");
                              const hasEditableMetadataSource = (file.source === "global" && Boolean(file.structuredFilename)) || [".md", ".markdown", ".txt"].includes((file.extension ?? "").toLowerCase());
                              const editDisabled = !hasEditableMetadataSource || ["queued", "queued_ocr", "parsing"].includes(file.parseStatus ?? "");

                              // generate a deterministic color for the book cover
                              const coverColors = ["bg-red-900", "bg-blue-900", "bg-emerald-900", "bg-amber-900", "bg-purple-900", "bg-teal-900", "bg-indigo-900", "bg-slate-800"];
                              const charCode = file.title.charCodeAt(0) || 0;
                              const coverColor = coverColors[Math.abs(charCode) % coverColors.length];

                              return (
                                <div 
                                  key={file.rowId}
                                  className={cn(
                                    "flex bg-white border border-slate-200 shadow-sm hover:shadow-[0_4px_16px_rgba(0,0,0,0.06)] transition-all group overflow-hidden min-h-[220px]",
                                    isSelected && "ring-2 ring-blue-500 border-transparent shadow-md"
                                  )}
                                >
                                  {/* Selection Checkbox (Floating) */}
                                  <div className="absolute opacity-0 group-hover:opacity-100 transition-opacity p-2.5 z-10 rounded-br-lg bg-white/90 border-b border-r border-slate-200 shadow-sm backdrop-blur-sm">
                                     <button
                                       type="button"
                                       className={cn("size-6 rounded flex items-center justify-center border bg-white transition-colors", isSelected ? "border-blue-500 text-blue-500 bg-blue-50 opacity-100" : "border-slate-300 text-transparent hover:text-slate-400")}
                                       onClick={() => toggleFileSelection(file.rowId)}
                                       disabled={!canSelectForChat}
                                     >
                                       {isSelected && <CheckSquareIcon className="size-5" />}
                                     </button>
                                  </div>
                                  {/* Also display the checkbox permanently if selected */}
                                  {isSelected && (
                                     <div className="absolute p-2.5 z-10 rounded-br-lg bg-white/90 border-b border-r border-slate-200 shadow-sm">
                                        <button type="button" className="size-6 rounded flex items-center justify-center border bg-blue-50 border-blue-500 text-blue-500" onClick={() => toggleFileSelection(file.rowId)}>
                                          <CheckSquareIcon className="size-5" />
                                        </button>
                                     </div>
                                  )}

                                  {/* Book Cover Pseudo-image */}
                                  <div className={cn("w-[210px] shrink-0 flex flex-col p-5 relative border-r border-slate-200 items-center justify-center", coverColor)}>
                                     {/* CSS Book spine reflection */}
                                     <div className="absolute left-0 top-0 bottom-0 w-4 bg-gradient-to-r from-black/50 via-white/10 to-transparent"></div>
                                     <div className="absolute left-4 top-0 bottom-0 w-[1px] bg-white/20"></div>
                                     <div className="absolute right-0 top-0 bottom-0 w-2 bg-black/30"></div>

                                     <div className="flex flex-col items-center justify-center inset-0 absolute">
                                        <div className="border border-white/20 p-5 w-36 h-[190px] flex flex-col items-center justify-center bg-black/20 shadow-inner">
                                           <span className="text-white text-[70px] opacity-40 mb-4 font-serif italic text-center w-full truncate block px-2 leading-none cursor-default select-none">
                                              {file.title?.charAt(0) ?? "?"}
                                           </span>
                                           <div className="h-px w-12 bg-white/30 mb-4"></div>
                                           <span className="text-[11px] tracking-widest font-sans opacity-70 text-white uppercase bg-black/30 px-2 py-0.5 rounded-sm">
                                              {file.extension?.replace('.', '') || 'UNKNOWN'}
                                           </span>
                                        </div>
                                     </div>
                                  </div>

                                  {/* Document Details Info */}
                                  <div className="flex-1 p-7 flex flex-col relative w-0">
                                     <div className="flex justify-between items-start gap-4 mb-6">
                                        <h3 className="text-[22px] font-bold text-slate-800 group-hover:text-blue-700 transition-colors line-clamp-2 leading-[1.4] pr-10">
                                          {canOpenReader && readerHref ? (
                                             <a href={readerHref} target="_blank" rel="noopener noreferrer">{file.title}</a>
                                          ) : (
                                             <span>{file.title}</span>
                                          )}
                                        </h3>
                                        {/* Status Tag */}
                                        <div className="shrink-0 pt-1">
                                            <span className="inline-flex py-1 px-3 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 border border-slate-200">
                                              {statusLabel(file.parseStatus)}
                                            </span>
                                        </div>
                                     </div>

                                     <div className="grid grid-cols-2 md:grid-cols-2 gap-y-4 gap-x-8 text-[15px] text-slate-600 w-full lg:w-[85%] mt-2">
                                       <div className="flex items-start gap-2">
                                         <span className="text-slate-400 w-24 shrink-0">主要责任者:</span>
                                         <span className="font-medium text-blue-600 truncate">-不详-</span>
                                       </div>
                                       <div className="flex items-start gap-2">
                                         <span className="text-slate-400 w-24 shrink-0">出版者:</span>
                                         <span className="font-medium text-slate-700 truncate">--</span>
                                       </div>
                                       <div className="flex items-start gap-2">
                                         <span className="text-slate-400 w-24 shrink-0">文献来源:</span>
                                         <span className="font-medium text-slate-700 truncate">{file.source === "global" ? "系统预置库" : "个人上传"}</span>
                                       </div>
                                       <div className="flex items-start gap-2">
                                         <span className="text-slate-400 w-24 shrink-0">收录时间:</span>
                                         <span className="font-medium text-slate-700 truncate">
                                           {(() => {
                                             try {
                                               const d = new Date(file.updatedAt);
                                               return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
                                             } catch (e) {
                                               return file.updatedAt?.toString() || '--';
                                             }
                                           })()}
                                         </span>
                                       </div>
                                       <div className="flex items-start gap-2">
                                         <span className="text-slate-400 w-24 shrink-0">文件大小:</span>
                                         <span className="font-medium text-slate-700 truncate">{formatBytes(file.size)}</span>
                                       </div>
                                       <div className="flex items-start gap-2">
                                         <span className="text-slate-400 w-24 shrink-0">文档类目:</span>
                                         <span className="font-medium text-slate-700 truncate">{documentTypeLabel(file.hints?.document_type_hint) || "普通文档"}</span>
                                       </div>
                                     </div>

                                     <div className="mt-auto pt-6 flex justify-end gap-3 items-center">
                                        <div className="flex gap-2">
                                          {file.source === "global" ? (
                                            <Button variant="outline" className="h-9 px-4 text-slate-500 hover:text-slate-800 border-slate-200 hover:bg-slate-50" disabled={editDisabled || updateMetadataMutation.isPending} onClick={() => openEditDialog(sortedGlobalFiles.find((candidate) => candidate.filename === file.filename)!)}>
                                              <PencilIcon className="size-4 mr-1.5" />属性标签
                                            </Button>
                                          ) : (
                                            <Button variant="outline" className="h-9 px-4 text-slate-500 hover:text-slate-800 border-slate-200 hover:bg-slate-50" disabled={personalSpaces.length <= 1} onClick={() => { setMovingRecord(file); setMoveTargetSpaceId(file.knowledgeSpaceId ?? defaultPersonalSpace?.id ?? ""); }}>
                                              <FolderIcon className="size-4 mr-1.5" />移动位置
                                            </Button>
                                          )}
                                          
                                          {canRetry && (
                                            <Button variant="outline" className="h-9 px-4 text-slate-500 hover:text-slate-800 border-slate-200 hover:bg-slate-50" disabled={retryMutation.isPending} onClick={() => void handleRetryIndexing(file.filename)}>
                                              {isRetrying ? <Loader2Icon className="size-4 animate-spin mr-1.5" /> : <RefreshCwIcon className="size-4 mr-1.5" />} 重试解析
                                            </Button>
                                          )}

                                          <Button variant="outline" className="h-9 px-4 text-slate-500 hover:text-red-700 hover:border-red-200 hover:bg-red-50" disabled={(file.source === "global" ? deleteMutation.isPending : deleteUserRecordMutation.isPending)} onClick={() => file.source === "global" ? void handleDelete(file.filename) : void handleDeletePersonalRecord(file.userRecordId ?? "")}>
                                            {isDeleting ? <Loader2Icon className="size-4 animate-spin mr-1.5" /> : <Trash2Icon className="size-4 mr-1.5" />} 删除文件
                                          </Button>
                                        </div>
                                        
                                        {canOpenReader && readerHref ? (
                                           <a href={readerHref} target="_blank" rel="noopener noreferrer" className="ml-3 flex items-center gap-1.5 border border-[#8f1818] bg-white text-[#8f1818] hover:bg-[#8f1818] hover:text-white text-[15px] font-medium px-6 py-2 transition-colors rounded shadow-sm hover:shadow-md">
                                              <FileIcon className="size-4" /> 查看详情
                                           </a>
                                        ) : (
                                           <button className="ml-3 flex items-center gap-1.5 border border-slate-300 text-slate-400 text-[15px] font-medium px-6 py-2 rounded cursor-not-allowed bg-slate-50">
                                              <FileIcon className="size-4" /> 尚未解析
                                           </button>
                                        )}
                                     </div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                       ) : (!hasCurrentLevelEntries ? (
                          <div className="flex flex-col items-center justify-center py-24 text-slate-400">
                             <FileIcon className="size-16 mb-4 text-slate-200" />
                             <p className="text-lg font-medium text-slate-500">此分类下暂无相关文献文档。</p>
                             <p className="text-sm mt-1">您可以尝试放宽检索范围或切换分类查看。</p>
                          </div>
                       ) : null)}
                     </div>
                   )}
               </div>
            </div>
          </section>\n"""

pattern = start_marker + r'.*?' + end_marker
new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

if count > 0:
    with open('/Users/lawkaiqing/code/history-rag/frontend/src/components/workspace/knowledge-management-page.tsx', 'w') as f:
        f.write(new_content)
    print("SUCCESS: Content replaced.")
else:
    print("ERROR: Start/End markers not found.")

