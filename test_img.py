import io
from PIL import Image, ImageDraw, ImageFont

def generate_impostor_win_image(num, imposter_names):
    if num == 1:
        template_path = "assets/guess-the-impostor/impostor-empty-frame.png"
        frames = [((401, 190), (598, 386))]
        texts = [((405, 425), (598, 460))]
    elif num == 2:
        template_path = "assets/guess-the-impostor/impostor-2-empty-frame.png"
        frames = [((270, 197), (464, 392)), ((535, 196), (732, 393))]
        texts = [((270, 426), (462, 464)), ((536, 420), (731, 460))]
    else:
        # Assuming 3
        template_path = "assets/guess-the-impostor/impostor-3-empty-frame.png"
        frames = [((135, 190), (332, 388)), ((401, 189), (597, 387)), ((666, 190), (865, 386))]
        texts = [((138, 418), (326, 452)), ((404, 411), (597, 450)), ((674, 415), (864, 451))]
        
    try:
        base_img = Image.open(template_path).convert("RGBA")
    except Exception as e:
        print(f"Error loading imposter template {template_path}: {e}")
        return None
        
    draw = ImageDraw.Draw(base_img)
    try:
        font = ImageFont.truetype("Arial.ttf", 24)
    except:
        font = ImageFont.load_default()
        
    for i in range(min(num, len(frames))):
        name = imposter_names[i]
        frame = frames[i]
        text_box = texts[i]
        
        # Test filling frame with red
        w = int(frame[1][0] - frame[0][0])
        h = int(frame[1][1] - frame[0][1])
        red_box = Image.new("RGBA", (w, h), (255, 0, 0, 255))
        base_img.paste(red_box, (int(frame[0][0]), int(frame[0][1])), red_box)
        
        # Draw text
        try:
            w_t = text_box[1][0] - text_box[0][0]
            h_t = text_box[1][1] - text_box[0][1]
            
            bbox = draw.textbbox((0, 0), name, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            
            tx = text_box[0][0] + (w_t - tw) / 2
            ty = text_box[0][1] + (h_t - th) / 2
            
            draw.text((tx, ty), name, fill="white", font=font)
        except Exception as e:
            print(f"Error drawing text: {e}")
            pass
            
    base_img.save(f"test_{num}.png", format="PNG")

if __name__ == '__main__':
    generate_impostor_win_image(1, ["Player1"])
    generate_impostor_win_image(2, ["Player1", "Player2"])
    generate_impostor_win_image(3, ["Player1", "Player2", "Player3"])
