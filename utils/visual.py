from itertools import groupby

import gradio as gr
from hooked_stream import hooked_read


def render_binary_file(file: gr.File) -> tuple[str, str]:
    """
    Render a binary file using the hooked_read functionality and display the contents.
    
    Args:
        file: A Gradio File object containing the binary file to analyze
        
    Returns:
        Tuple[str, str]: A tuple containing:
            - The hex dump of the file contents
            - A formatted block analysis showing the structure
    """
    try:
        # Read the binary file
        blocks = hooked_read(file.name)
        
        # Generate hex dump
        hex_dump = ""
        block_analysis = ""
        
        for i, (block, start, end, hex_data, traces) in enumerate(blocks):
            block_name = type(block).__name__
            
            # Format block info
            block_analysis += f"Block {i}: {block_name}\n"
            block_analysis += f"Start: {start}, End: {end}, Size: {end-start} bytes\n"
            for call_stack, traces in groupby(traces, key=lambda x: " -> ".join(x[-1])):
                block_analysis += f"  {call_stack}\n"
                for trace in traces:
                    _, read_size, subblock_hex, frames = trace
                    block_analysis += f"    read {read_size} bytes {len(frames)} frames\n"
                # for frame in frames:
                #     block_analysis += f"    {frame}\n"
            block_analysis += "-" * 50 + "\n"
            
            # Format hex dump with line numbers and ASCII
            hex_dump += f"\n=== Block {i}: {block_name} ===\n"
            for j in range(0, len(hex_data), 32):
                line = hex_data[j:j+32]
                offset = j//2
                ascii_chars = ''.join(chr(int(line[i:i+2], 16)) if 32 <= int(line[i:i+2], 16) <= 126 else '.' 
                                    for i in range(0, len(line), 2))
                hex_dump += f"{offset:08x}: {' '.join(line[i:i+2] for i in range(0, len(line), 2)):48s}  {ascii_chars}\n"
                
        return hex_dump, block_analysis
        
    except Exception as e:
        return f"Error processing file: {str(e)}", ""

def create_ui() -> gr.Blocks:
    """
    Create the Gradio interface for the binary file renderer.
    
    Returns:
        gr.Blocks: The configured Gradio interface
    """
    with gr.Blocks(title="Binary File Renderer") as app:
        gr.Markdown("# Binary File Renderer")
        gr.Markdown("Upload a binary file to analyze its structure and contents")
        
        with gr.Row():
            file_input = gr.File(label="Upload Binary File")
            
        with gr.Row():
            hex_output = gr.Code(
                label="Hex Dump", 
                language="markdown",
                lines=20,
                wrap=True
            )
            block_output = gr.Code(
                label="Block Analysis",
                language="markdown", 
                lines=20,
                wrap=True
            )
            
        file_input.change(
            fn=render_binary_file,
            inputs=[file_input],
            outputs=[hex_output, block_output]
        )
        
    return app

if __name__ == "__main__":
    app = create_ui()
    app.launch()
