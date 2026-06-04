import os

def search_text(path, text):
    for root, dirs, files in os.walk(path):
        if '.venv' in root or '.git' in root or '__pycache__' in root:
            continue
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        for i, line in enumerate(lines):
                            if text in line:
                                print(f"{filepath}:{i+1}: {line.strip()}")
                except Exception as e:
                    pass

if __name__ == "__main__":
    search_text("C:\\Users\\brad3\\Proyectos\\Proyecto-SI2-Examen-1\\taller-backend", "Bitacora")
