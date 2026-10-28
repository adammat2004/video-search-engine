"""Build an exact inner-product FAISS index over the (L2-normalised) image embeddings."""
import faiss
import numpy as np

from common import build_step, config, is_fresh


def main():
    if is_fresh([config.FAISS_INDEX], [config.IMG_EMB]):
        print("[build_faiss] up to date"); return
    with build_step("build_faiss", outputs=[config.FAISS_INDEX]) as info:
        emb = np.load(config.IMG_EMB).astype(np.float32)
        index = faiss.IndexFlatIP(emb.shape[1])
        index.add(emb)
        faiss.write_index(index, str(config.FAISS_INDEX))
        info.update(ntotal=index.ntotal, dim=index.d)


if __name__ == "__main__":
    main()
