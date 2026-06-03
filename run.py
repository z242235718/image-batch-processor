# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
