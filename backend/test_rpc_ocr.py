import grpc
import os
import sys

# 导入由统一的 mineru.proto 生成的桩代码
import mineru_pb2
import mineru_pb2_grpc

def run_test():
    # 1. 🚨 配置 1GB 的传输上限，确保能发送和接收超大 PDF
    MAX_SIZE = 1024 * 1024 * 1024
    options = [
        ('grpc.max_send_message_length', MAX_SIZE),
        ('grpc.max_receive_message_length', MAX_SIZE)
    ]

    # 2. 你的 M2 Ultra 内网 IP 和端口
    target = '10.104.45.160:50051' 
    
    print(f"🔗 正在连接到 gRPC 服务端: {target}...")
    
    try:
        # 建立 gRPC 通道
        with grpc.insecure_channel(target, options=options) as channel:
            stub = mineru_pb2_grpc.MineruPdfExtractorStub(channel)

            # 3. 读取本地测试用的 PDF 文件
            test_file = "demo.pdf"  
            if not os.path.exists(test_file):
                print(f"❌ 找不到测试文件 '{test_file}'，请先在当前脚本同目录下放一个名为 demo.pdf 的文件！")
                sys.exit(1)

            with open(test_file, 'rb') as f:
                pdf_bytes = f.read()

            print(f"📤 正在发送文件: {test_file} (大小: {len(pdf_bytes)/1024/1024:.2f} MB)")

            # 4. 严格按照你同事定义的字段组装请求
            # 如果 proto 里定义的请求消息名不叫 ParsePdfRequest，请修改这里
            request = mineru_pb2.ParsePdfRequest(
                filename=test_file,
                file_content=pdf_bytes,
                language_hint="zh",           
                layout_hint="horizontal",     
                document_type_hint="book",    
                model_version="vlm"           
            )
            
            # [可选] 如果服务端需要鉴权，取消注释下面这行并传入你们的 token
            # metadata = (('authorization', 'Bearer YOUR_TOKEN_HERE'),)
            # response = stub.ParsePdf(request, metadata=metadata)
            
            # 5. 发起远程调用 (会阻塞等待 M2 Ultra 解析完成)
            print("⏳ 正在等待 M2 Ultra 算力节点解析中...")
            print("   (如果文件很大，这可能需要几分钟，请耐心等待)")
            response = stub.ParsePdf(request)

            # 6. 验证返回的结构化数据
            print("\n🎉 解析完成，成功收到响应！")
            print(f"📌 任务 ID: {response.task_id}")
            
            doc = response.document
            print(f"📄 总页数: {len(doc.pages)}")
            
            # 如果成功获取了结构化分页数据，展示第一页的细节
            if len(doc.pages) > 0:
                first_page = doc.pages[0]
                print(f"\n🔍 第一页 (PDF物理页码: {first_page.pdf_page_no}) 包含 {len(first_page.paragraphs)} 个段落。")
                
                # 打印前 3 个段落的坐标和文本，验证 bbox 是否生效
                for i, para in enumerate(first_page.paragraphs[:3]):
                    print(f"\n  ➤ 段落 {i+1}:")
                    print(f"    坐标: x={para.bbox.x}, y={para.bbox.y}, width={para.bbox.width}, height={para.bbox.height}")
                    # 截取前 50 个字符展示，并将换行符替换为空格防止刷屏
                    safe_text = para.text[:50].replace('\n', ' ')
                    print(f"    文本: {safe_text}...") 
            else:
                print("\n⚠️ 警告：返回的文档没有 pages 结构化数据，可能降级到了 full_text 兜底模式。")
                if hasattr(doc, 'full_text') and doc.full_text:
                    print(f"兜底文本前 100 字:\n{doc.full_text[:100]}...")
                else:
                    print("❌ 返回的数据完全为空，请检查服务端解析日志！")

            print("\n✅ 链路联调测试完美结束。")

    except grpc.RpcError as e:
        print(f"\n❌ gRPC 调用失败！")
        print(f"状态码: {e.code()}")
        print(f"详细报错信息: {e.details()}")

if __name__ == '__main__':
    run_test()