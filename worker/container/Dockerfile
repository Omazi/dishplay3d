# Compiled on GitHub. Local execution is CPU-only inside an explicitly bounded container.
FROM ubuntu:22.04 AS build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake ninja-build git ca-certificates curl xz-utils \
    libboost-program-options-dev libboost-graph-dev libboost-system-dev libboost-iostreams-dev libboost-serialization-dev \
    libeigen3-dev libflann-dev libfreeimage-dev libmetis-dev libgoogle-glog-dev libgtest-dev libsqlite3-dev \
    libglew-dev libcgal-dev libceres-dev libopencv-dev libjpeg-dev libpng-dev libtiff-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN git init colmap && cd colmap && git remote add origin https://github.com/colmap/colmap.git \
    && git fetch --depth 1 origin 682ea9ac4020a143047758739259b3ff04dabe8d && git checkout FETCH_HEAD \
    && cmake -S . -B build -GNinja -DCMAKE_BUILD_TYPE=Release -DCUDA_ENABLED=OFF -DGUI_ENABLED=OFF -DTESTS_ENABLED=OFF \
    && cmake --build build --parallel 2 && cmake --install build
RUN git init vcg && cd vcg && git remote add origin https://github.com/cdcseacave/VCG.git \
    && git fetch --depth 1 origin 10d73fc962f99bf5e3ca2c26ee1c8d417b0c3c9a && git checkout FETCH_HEAD
RUN git init openmvs && cd openmvs && git remote add origin https://github.com/cdcseacave/openMVS.git \
    && git fetch --depth 1 origin ce03889e2055a3d6cbcae9dd5a93b5eeea94b909 && git checkout FETCH_HEAD \
    && cmake -S . -B build -GNinja -DCMAKE_BUILD_TYPE=Release -DVCG_ROOT=/build/vcg \
       -DOpenMVS_USE_CUDA=OFF -DOpenMVS_USE_OPENGL=OFF -DOpenMVS_USE_BREAKPAD=OFF -DOpenMVS_USE_PYTHON=OFF -DOpenMVS_ENABLE_TESTS=OFF \
    && cmake --build build --parallel 1 && cmake --install build
RUN curl -fL --retry 3 https://download.blender.org/release/Blender4.5/blender-4.5.13-linux-x64.tar.xz -o blender.tar.xz \
    && echo 'da4e69b06b75b9e642d106496c50e7e240218b411d2f6e18271c1d1d819cef91  blender.tar.xz' | sha256sum -c - \
    && mkdir /opt/blender && tar -xJf blender.tar.xz --strip-components=1 -C /opt/blender

FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    QT_QPA_PLATFORM=offscreen CUDA_VISIBLE_DEVICES=-1 PYTHONDONTWRITEBYTECODE=1 \
    PATH=/usr/local/bin/OpenMVS:/opt/blender:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates \
    libboost-program-options1.74.0 libboost-graph1.74.0 libboost-system1.74.0 libboost-iostreams1.74.0 libboost-serialization1.74.0 \
    libfreeimage3 libmetis5 libgoogle-glog0v5 libsqlite3-0 libglew2.2 libceres2 libopencv-core4.5d libopencv-imgcodecs4.5d \
    libopencv-imgproc4.5d libopencv-highgui4.5d libopencv-calib3d4.5d libgomp1 libgl1 libegl1 libxrender1 libxi6 libxfixes3 libxkbcommon0 libsm6 \
    && python3 -m pip install --no-cache-dir Pillow==12.3.0 && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local/ /usr/local/
COPY --from=build /opt/blender /opt/blender
RUN ldconfig && colmap -h >/dev/null && blender --background --version \
    && (DensifyPointCloud --help >/tmp/openmvs-help 2>&1 || test $? -eq 1) \
    && grep -q 'OpenMVS.*2.3.0' /tmp/openmvs-help && rm /tmp/openmvs-help
ENTRYPOINT ["python3"]
